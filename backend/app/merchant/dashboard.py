"""Dashboard report: every number and chart on the Dashboard page, for one set of slicers.

Slicers: a date range, a branch, a payment status, and chart clicks (a day, a risk zone, an hour x weekday cell).
Order-based figures (sales, refunds, money in the bank) follow the date range, branch and day. Payment-based
figures (status, busy hours, risk zones, "looks risky") also follow status, zone and hour x weekday. A chart that
draws one of those slicers ignores that slicer itself, so a click highlights a bar instead of hiding the others.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .analytics import _primary
from .model import MerchantDataset

# Reconciliation findings that mean money was expected but is not in the bank yet.
NOT_RECEIVED_TYPES = {"pending_payment", "order_without_payment", "settlement_shortfall"}
ZONES = {"low": "safe", "medium": "check", "high": "fraud"}
MAX_SPARK_DAYS = 45


def _window(ds: MerchantDataset, date_from: str | None, date_to: str | None) -> tuple[pd.Timestamp, pd.Timestamp]:
    """[start, end) from the slicer; the default is the last 30 days of the data."""
    end = (pd.Timestamp(date_to) if date_to else ds.anchor.normalize()) + pd.Timedelta(days=1)
    start = pd.Timestamp(date_from) if date_from else end - pd.Timedelta(days=30)
    start = max(start, ds.transactions["ts"].min().normalize())
    return start, max(end, start + pd.Timedelta(days=1))


def _in(df: pd.DataFrame, col: str, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
    return df[(df[col] >= a) & (df[col] < b)]


def _money(s: pd.Series) -> int:
    return int(s.sum()) if len(s) else 0


class _Data:
    """The dataset's frames with branch and risk zone resolved once."""

    def __init__(self, ds: MerchantDataset) -> None:
        self.ds = ds
        tx = _primary(ds).copy()
        if ds.risk is None:
            tx["zone"] = "safe"
        else:
            tx["zone"] = tx["tid"].map(ds.risk["level"]).map(ZONES).fillna("safe")
        self.tx = tx
        self.orders = ds.orders
        ref = ds.refunds.copy()
        owner = ds.transactions.drop_duplicates("txn_ref").set_index("txn_ref")["outlet"]
        ref["outlet"] = ref["txn_ref"].map(owner) if not ref.empty else pd.Series(dtype=str)
        self.refunds = ref
        self.settlements = ds.settlements

    def series(self, a: pd.Timestamp, b: pd.Timestamp, step: int, branch: str | None) -> list[dict[str, Any]]:
        """The same five measures per bucket of `step` days, in one grouped pass instead of one pass per bucket."""
        ds = self.ds
        tx, orders, ref = _in(self.tx, "ts", a, b), _in(self.orders, "ts", a, b), _in(self.refunds, "ts", a, b)
        if branch:
            tx, orders, ref = tx[tx["outlet"] == branch], orders[orders["outlet"] == branch], ref[ref["outlet"] == branch]
        paid = tx[tx["status"] == "success"]
        n = (b - a).days
        bucket = lambda ts: ((ts.dt.normalize() - a).dt.days // step).clip(0, (n - 1) // step)  # noqa: E731

        def per(df: pd.DataFrame, col: str, value: str | None) -> pd.Series:
            if df.empty:
                return pd.Series(dtype="int64")
            g = df.groupby(bucket(df[col]))
            return g[value].sum() if value else g.size()

        sales = per(orders, "ts", "amount_paise") if ds.has_orders else per(paid, "ts", "amount_paise")
        in_bank = per(self.settlements[(self.settlements["date"] >= a) & (self.settlements["date"] < b)], "date", "amount_paise") if ds.has_settlements and not branch else per(paid, "ts", "amount_paise")
        missing = pd.Series(0, index=range(len(range(0, n, step))), dtype="int64")
        for x in ds.discrepancies:
            t = pd.Timestamp(x["ts"])
            if x["type"] in NOT_RECEIVED_TYPES and a <= t < b and (not branch or x["outlet"] == branch):
                missing.iloc[min((t.normalize() - a).days // step, len(missing) - 1)] += x["amount_at_stake_paise"]
        cols = {"sales": sales, "in_bank": in_bank, "refunded": per(ref, "ts", "amount_paise"), "not_received": missing, "risky": per(tx[tx["zone"] != "safe"], "ts", None)}
        idx = range(len(missing))
        return [{"date": (a + pd.Timedelta(days=i * step)).date().isoformat(), **{k: int(v.get(i, 0)) for k, v in cols.items()}} for i in idx]

    def measures(self, a: pd.Timestamp, b: pd.Timestamp, branch: str | None) -> dict[str, int]:
        ds = self.ds
        tx, orders, ref = _in(self.tx, "ts", a, b), _in(self.orders, "ts", a, b), _in(self.refunds, "ts", a, b)
        if branch:
            tx, orders, ref = tx[tx["outlet"] == branch], orders[orders["outlet"] == branch], ref[ref["outlet"] == branch]
        paid = tx[tx["status"] == "success"]
        sales = _money(orders["amount_paise"]) if ds.has_orders else _money(paid["amount_paise"])
        # Settlements are per day, not per branch, so a branch view falls back to its payments marked successful.
        if ds.has_settlements and not branch:
            in_bank = _money(_in(self.settlements, "date", a, b)["amount_paise"])
        else:
            in_bank = _money(paid["amount_paise"])
        refunded = _money(ref["amount_paise"])
        missing = sum(x["amount_at_stake_paise"] for x in ds.discrepancies if x["type"] in NOT_RECEIVED_TYPES and a <= pd.Timestamp(x["ts"]) < b and (not branch or x["outlet"] == branch))
        return {"sales": sales, "in_bank": in_bank, "refunded": refunded, "not_received": int(missing), "risky": int((tx["zone"] != "safe").sum())}


def build(ds: MerchantDataset, *, date_from: str | None, date_to: str | None, branch: str | None, status: str | None,
          zone: str | None, hour: int | None, dow: int | None, day: str | None) -> dict[str, Any]:
    d = _Data(ds)
    a, b = _window(ds, date_from, date_to)
    if day:
        a, b = max(a, pd.Timestamp(day)), min(b, pd.Timestamp(day) + pd.Timedelta(days=1))
        b = max(b, a + pd.Timedelta(days=1))
    span = b - a
    cur = d.measures(a, b, branch)
    prev = d.measures(a - span, a, branch)

    full_prev = a - span >= ds.transactions["ts"].min().normalize()  # no comparison when the data starts inside the previous period

    def card(key: str) -> dict[str, Any]:
        p = prev[key]
        return {"value": cur[key], "change": None if not p or not full_prev else round((cur[key] - p) / p, 3)}

    # daily series (weekly when the range is long) for the sparklines and the sales-vs-bank chart
    days = pd.date_range(a, b - pd.Timedelta(days=1), freq="D")
    step = 1 if len(days) <= MAX_SPARK_DAYS else 7
    series = d.series(a, b, step, branch)

    def pay(skip: str | None = None) -> pd.DataFrame:
        """Payments in the window with every payment slicer applied except `skip`."""
        t = _in(d.tx, "ts", a, b)
        if branch and skip != "branch":
            t = t[t["outlet"] == branch]
        if status and skip != "status":
            t = t[t["status"] == status]
        if zone and skip != "zone":
            t = t[t["zone"] == zone]
        if hour is not None and dow is not None and skip != "heat":
            t = t[(t["ts"].dt.hour == hour) & (t["ts"].dt.dayofweek == dow)]
        return t

    statuses = [{"id": s, "count": int(n), "amount_paise": int(v)} for s, (n, v) in pay("status").groupby("status")["amount_paise"].agg(["size", "sum"]).iterrows()]
    zt = pay("zone")["zone"]
    zones = {z: int((zt == z).sum()) for z in ("safe", "check", "fraud")}
    heat = pay("heat")
    grid = heat.groupby([heat["ts"].dt.dayofweek, heat["ts"].dt.hour]).size()
    heatmap = [{"dow": int(k[0]), "hour": int(k[1]), "count": int(v)} for k, v in grid.items()]

    # Sales by branch: orders when there are orders, else payments marked successful. Ignores the branch slicer so every branch stays visible.
    src = _in(d.orders, "ts", a, b) if ds.has_orders else _in(d.tx, "ts", a, b).query("status == 'success'")
    branches = [{"id": k, "amount_paise": int(v)} for k, v in src.groupby("outlet")["amount_paise"].sum().sort_values(ascending=False).head(8).items()]

    owner = ds.transactions.set_index("tid")["outlet"]
    urgent = [x for x in ds.actions if a <= pd.Timestamp(x["ts"]) < b + pd.Timedelta(days=1) and (not branch or any(owner.get(t) == branch for t in x.get("tids", [])))]
    urgent.sort(key=lambda x: -x["priority"])
    attention = [x for x in ds.discrepancies if a <= pd.Timestamp(x["ts"]) < b and (not branch or x["outlet"] == branch)]
    return {
        "from": a.date().isoformat(), "to": (b - pd.Timedelta(days=1)).date().isoformat(),
        "data_start": ds.transactions["ts"].min().date().isoformat(), "data_end": ds.anchor.date().isoformat(),
        "branches_all": sorted(ds.transactions["outlet"].unique().tolist()),
        "has_orders": ds.has_orders, "has_settlements": ds.has_settlements, "bank_basis": "settlements" if ds.has_settlements and not branch else "payments",
        "kpis": {k: card(k) for k in ("sales", "in_bank", "refunded", "not_received", "risky")},
        "needs_attention_paise": int(sum(x["amount_at_stake_paise"] for x in attention)), "needs_attention_count": len(attention),
        "series": series, "waterfall": {"sales": cur["sales"], "refunded": cur["refunded"], "not_received": cur["not_received"], "other": cur["in_bank"] - (cur["sales"] - cur["refunded"] - cur["not_received"]), "in_bank": cur["in_bank"]},
        "statuses": statuses, "branches": branches, "heatmap": heatmap, "zones": zones, "payments_in_view": int(len(pay())),
        "top_items": [{"id": x["id"], "title": x["title"], "summary": x["summary"], "paise": x["amount_at_stake_paise"], "severity": x["severity"], "ts": x["ts"]} for x in urgent[:5]],
    }
