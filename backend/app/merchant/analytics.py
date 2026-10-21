"""KPIs, trends and transaction queries. One source of truth: the KPI cards, charts and tables all read the same
frames through the same window and filter helpers, so their numbers agree by construction.

Periods are relative to the dataset's latest timestamp ("data end"), not to today's date, so a dataset from
last year still shows its last 7 / 30 days. The UI states the data end date.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .model import MerchantDataset

PERIOD_DAYS = {"day": 1, "week": 7, "month": 30, "all": None}
UNMATCHED_TYPES = {"order_without_payment", "payment_without_order", "ambiguous_match"}

DEFINITIONS = {
    "recorded_sales": "Total of the orders recorded in the period (what you say you sold). Needs order records.",
    "confirmed_payments": "Total of payments marked successful in your payment records. This is NOT a bank credit; it is only as reliable as those records.",
    "payment_volume": "Total value of every payment attempt (successful, failed, pending and reversed).",
    "success_rate": "Successful payments divided by all payment attempts, by count.",
    "refunds_total": "Total of refunds recorded in the period.",
    "settled": "Total of settlement (bank credit) records in the period. Needs settlement records.",
    "unmatched": "Orders with no matching payment plus payments with no matching order, found by the reconciliation rules. Unverified.",
    "discrepancy_amount": "Amount involved in all discrepancies the rules found in the period. A flag, not a confirmed loss: records can disagree for ordinary reasons.",
    "alerts": "Transactions in the top 5% of the risk-model score or of the unusual-activity score in this data (so roughly one in ten). For review; not a verdict.",
}


def window(ds: MerchantDataset, period: str) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp | None, pd.Timestamp | None]:
    """[start, end) of the period and of the equally long period before it (None for 'all')."""
    end = ds.anchor.normalize() + pd.Timedelta(days=1)
    days = PERIOD_DAYS[period]
    if days is None:
        return ds.transactions["ts"].min().normalize(), end, None, None
    start = end - pd.Timedelta(days=days)
    return start, end, start - pd.Timedelta(days=days), start


def _in(df: pd.DataFrame, col: str, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
    return df[(df[col] >= a) & (df[col] < b)]


def _primary(ds: MerchantDataset) -> pd.DataFrame:
    return ds.transactions[~ds.transactions["is_dup_row"]]


def _alerts(ds: MerchantDataset) -> pd.DataFrame:
    if ds.risk is None:
        return pd.DataFrame(columns=["alert"])
    return ds.risk[ds.risk["alert"]]


def _measures(ds: MerchantDataset, a: pd.Timestamp, b: pd.Timestamp) -> dict[str, int | None]:
    tx = _in(_primary(ds), "ts", a, b)
    ok = tx[tx["status"] == "success"]
    n = len(tx)
    disc = [d for d in ds.discrepancies if a <= pd.Timestamp(d["ts"]) < b]
    alert_ids = set(_alerts(ds).index)
    return {
        "recorded_sales": int(_in(ds.orders, "ts", a, b)["amount_paise"].sum()) if ds.has_orders else None,
        "confirmed_payments": int(ok["amount_paise"].sum()),
        "confirmed_count": len(ok),
        "payment_volume": int(tx["amount_paise"].sum()),
        "attempts": n,
        "success_rate": None if n == 0 else int(round(10000 * len(ok) / n)),  # basis points, avoids float drift
        "failed": int((tx["status"] == "failed").sum()), "pending": int((tx["status"] == "pending").sum()), "reversed": int((tx["status"] == "reversed").sum()),
        "refunds_total": int(_in(ds.refunds, "ts", a, b)["amount_paise"].sum()), "refunds_count": len(_in(ds.refunds, "ts", a, b)),
        "settled": int(_in(ds.settlements, "date", a, b)["amount_paise"].sum()) if ds.has_settlements else None,
        "unmatched": sum(1 for d in disc if d["type"] in UNMATCHED_TYPES),
        "discrepancy_amount": int(sum(d["amount_at_stake_paise"] for d in disc)), "discrepancy_count": len(disc),
        "alerts": int(tx["tid"].isin(alert_ids).sum()),
    }


def overview(ds: MerchantDataset, period: str) -> dict[str, Any]:
    a, b, pa, pb = window(ds, period)
    cur = _measures(ds, a, b)
    prev = _measures(ds, pa, pb) if pa is not None else None

    def kpi(key: str, label: str, unit: str, tone: str = "neutral", sub: str | None = None) -> dict[str, Any]:
        v, p = cur[key], (prev[key] if prev else None)
        ch = None if v is None or p in (None, 0) else round(100 * (v - p) / p, 1)
        return {"key": key, "label": label, "unit": unit, "value": v, "previous": p, "change_pct": ch, "tone": tone, "definition": DEFINITIONS.get(key, ""), "sub": sub}

    kpis = [
        kpi("recorded_sales", "Recorded sales", "money", "primary"),
        kpi("confirmed_payments", "Confirmed payments", "money", "ok", f"{cur['confirmed_count']} payments"),
        kpi("success_rate", "Payment success rate", "bps", "neutral", f"{cur['attempts']} attempts"),
        kpi("refunds_total", "Refunds", "money", "warn", f"{cur['refunds_count']} refunds"),
        kpi("settled", "Settled to bank", "money", "neutral"),
        kpi("unmatched", "Unmatched records", "count", "warn"),
        kpi("discrepancy_amount", "Amount in flagged discrepancies", "money", "bad", f"{cur['discrepancy_count']} items, unverified"),
        kpi("alerts", "Alerts to review", "count", "bad"),
    ]
    status = [{"status": s, "count": int(c), "amount_paise": int(v)} for s, (c, v) in _in(_primary(ds), "ts", a, b).groupby("status")["amount_paise"].agg(["size", "sum"]).iterrows()]
    tx = _in(_primary(ds), "ts", a, b)
    ok = tx[tx["status"] == "success"]
    disc_by_outlet = pd.Series([d["outlet"] for d in ds.discrepancies if d["outlet"] and a <= pd.Timestamp(d["ts"]) < b]).value_counts()
    outlets = [{"outlet": o, "confirmed_paise": int(g["amount_paise"].sum()), "payments": len(g), "attempts": int((tx["outlet"] == o).sum()), "discrepancies": int(disc_by_outlet.get(o, 0))}
               for o, g in ok.groupby("outlet")]
    outlets.sort(key=lambda r: -r["confirmed_paise"])
    return {
        "period": period, "from": a.isoformat(), "to": (b - pd.Timedelta(seconds=1)).isoformat(), "previous_from": None if pa is None else pa.isoformat(),
        "data_end": ds.anchor.isoformat(), "kpis": kpis, "status_breakdown": status, "top_outlets": outlets[:6], "outlet_count": ds.transactions["outlet"].nunique(),
        "unusual_days": (ds.unusual or unusual_days(ds))[:5],
    }


def _bucket(ts: pd.Series, g: str) -> pd.Series:
    d = ts.dt.normalize()
    if g == "week":
        return d - pd.to_timedelta(d.dt.dayofweek, unit="D")
    if g == "month":
        return d - pd.to_timedelta(d.dt.day - 1, unit="D")
    return d


def series(ds: MerchantDataset, granularity: str, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> list[dict[str, Any]]:
    """Per-bucket totals with every bucket present (zeros included), so charts have no silent gaps."""
    end = end or (ds.anchor.normalize() + pd.Timedelta(days=1))
    default_days = {"day": 90, "week": 7 * 52, "month": 3650}[granularity]
    start = start or max(ds.transactions["ts"].min().normalize(), end - pd.Timedelta(days=default_days))
    tx = _in(_primary(ds), "ts", start, end)
    ok = tx[tx["status"] == "success"]
    parts: dict[str, pd.Series] = {}

    def add(name: str, df: pd.DataFrame, col: str, value: str | None) -> None:
        if df.empty:
            parts[name] = pd.Series(dtype="int64")
            return
        b = _bucket(df[col], granularity)
        parts[name] = (df.groupby(b)[value].sum() if value else df.groupby(b).size()).astype("int64")

    add("recorded_sales", _in(ds.orders, "ts", start, end), "ts", "amount_paise")
    add("confirmed", ok, "ts", "amount_paise")
    add("refunds", _in(ds.refunds, "ts", start, end), "ts", "amount_paise")
    add("attempts", tx, "ts", None)
    add("failed", tx[tx["status"] == "failed"], "ts", None)
    disc = pd.DataFrame({"ts": [pd.Timestamp(d["ts"]) for d in ds.discrepancies]})
    add("discrepancies", _in(disc, "ts", start, end) if len(disc) else disc.assign(ts=pd.to_datetime(disc["ts"])), "ts", None)
    alert_tx = tx[tx["tid"].isin(set(_alerts(ds).index))]
    add("alerts", alert_tx, "ts", None)
    first = _bucket(pd.Series([start]), granularity).iloc[0]
    idx = pd.date_range(first, end - pd.Timedelta(seconds=1), freq={"day": "D", "week": "7D", "month": "MS"}[granularity])
    df = pd.DataFrame(parts).reindex(idx).fillna(0).astype("int64")
    return [{"date": d.date().isoformat(), **{c: int(v) for c, v in r.items()}} for d, r in df.iterrows()]


def unusual_days(ds: MerchantDataset) -> list[dict[str, Any]]:
    """Days whose total is far from the trailing 28-day pattern (robust z >= 3.5, needs 14 days of history)."""
    s = series(ds, "day", start=ds.transactions["ts"].min().normalize())
    col = "recorded_sales" if ds.has_orders else "confirmed"
    v = pd.Series([r[col] for r in s], index=pd.to_datetime([r["date"] for r in s]), dtype=float)
    out = []
    for i in range(14, len(v)):
        hist = v.iloc[max(0, i - 28):i]
        med = hist.median()
        mad = max((hist - med).abs().median() * 1.4826, 0.15 * med, 1.0)
        z = (v.iloc[i] - med) / mad
        if abs(z) >= 3.5 and (v.iloc[i] > 0 or med > 0):
            out.append({"date": v.index[i].date().isoformat(), "value_paise": int(v.iloc[i]), "typical_paise": int(med), "direction": "above" if z > 0 else "below", "z": round(float(z), 1), "metric": col})
    return sorted(out, key=lambda r: r["date"], reverse=True)


# --------------------------------------------------------------------------- #
# transaction table
# --------------------------------------------------------------------------- #
def mask_ref(s: Any) -> str | None:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    s = str(s)
    return "…" + s[-4:] if len(s) > 4 else s


def txn_frame(ds: MerchantDataset) -> pd.DataFrame:
    tx = ds.transactions
    f = tx[["tid", "txn_ref", "ts", "amount_paise", "status", "outlet", "order_id", "payer_ref", "is_dup_row"]].copy()
    rf = ds.refunds.groupby("txn_ref")["amount_paise"].sum() if not ds.refunds.empty else pd.Series(dtype="int64")
    f["refund_paise"] = f["txn_ref"].map(rf).fillna(0).astype("int64")
    count: dict[str, int] = {}
    for d in ds.discrepancies:
        for t in d["tids"]:
            count[t] = count.get(t, 0) + 1
    f["discrepancies"] = f["tid"].map(count).fillna(0).astype(int)
    if ds.risk is not None:
        r = ds.risk
        f["risk_level"], f["risk_score"], f["risk_signal"] = f["tid"].map(r["level"]), f["tid"].map(r["score"]), f["tid"].map(r["signal"])
    else:
        f["risk_level"], f["risk_score"], f["risk_signal"] = None, np.nan, "none"
    return f


def query_transactions(ds: MerchantDataset, *, date_from: str | None, date_to: str | None, status: list[str], outlet: str | None, risk: str | None, discrepancy: bool | None,
                       q: str | None, sort: str, desc: bool, page: int, page_size: int, tab: str | None = None) -> dict[str, Any]:
    f = txn_frame(ds)
    if tab == "received":
        f = f[f["status"] == "success"]
    elif tab == "refunded":
        f = f[f["refund_paise"] > 0]
    elif tab == "not_received":
        f = f[f["status"].isin(["failed", "pending"])]
    elif tab == "risky":
        f = f[f["risk_level"].isin(["medium", "high"])]
    if date_from:
        f = f[f["ts"] >= pd.Timestamp(date_from)]
    if date_to:
        f = f[f["ts"] < pd.Timestamp(date_to) + pd.Timedelta(days=1)]
    if status:
        f = f[f["status"].isin(status)]
    if outlet:
        f = f[f["outlet"] == outlet]
    if risk == "alerts":
        f = f[f["risk_level"].isin(["medium", "high"])]
    elif risk in ("high", "medium", "low"):
        f = f[f["risk_level"] == risk]
    if discrepancy is True:
        f = f[f["discrepancies"] > 0]
    elif discrepancy is False:
        f = f[f["discrepancies"] == 0]
    if q:
        needle = q.strip().lower()
        hay = f["tid"].str.lower().str.contains(needle, regex=False) | f["order_id"].fillna("").str.lower().str.contains(needle, regex=False) | f["payer_ref"].fillna("").str.lower().str.contains(needle, regex=False)
        f = f[hay]
    key = {"ts": "ts", "amount": "amount_paise", "risk": "risk_score"}[sort]
    f = f.sort_values([key, "tid"], ascending=[not desc, True], kind="stable", na_position="last")
    total = len(f)
    pg = f.iloc[(page - 1) * page_size: page * page_size]
    rows = [{
        "tid": r.tid, "txn_ref": r.txn_ref, "ts": r.ts.isoformat(), "amount_paise": int(r.amount_paise), "status": r.status, "outlet": r.outlet, "order_id": r.order_id,
        "payer": mask_ref(r.payer_ref), "refund_paise": int(r.refund_paise), "discrepancies": int(r.discrepancies), "is_duplicate_row": bool(r.is_dup_row),
        "risk_level": r.risk_level if isinstance(r.risk_level, str) else None, "risk_score": None if pd.isna(r.risk_score) else round(float(r.risk_score), 1), "risk_signal": r.risk_signal,
    } for r in pg.itertuples()]
    return {"total": total, "page": page, "page_size": page_size, "rows": rows, "sum_amount_paise": int(f["amount_paise"].sum()), "sum_confirmed_paise": int(f.loc[f["status"] == "success", "amount_paise"].sum())}


def fraud_inputs(ds: MerchantDataset, r: pd.Series) -> dict[str, Any]:
    """The Fraud check form, pre-filled from this payer's own earlier payments (what a merchant can really know)."""
    tx = ds.transactions
    amount = r["amount_paise"] / 100
    hour = r["ts"].hour
    prior = tx[(tx["payer_ref"] == r["payer_ref"]) & (tx["ts"] < r["ts"]) & ~tx["is_dup_row"]] if r["payer_ref"] else tx.iloc[0:0]
    ok = prior[prior["status"] == "success"]
    gap_h = None if prior.empty else (r["ts"] - prior["ts"].max()).total_seconds() / 3600
    last = "never" if prior.empty else "hour" if gap_h < 1 else "today" if gap_h < 24 else "week" if gap_h < 24 * 7 else "older"
    return {
        "amount": round(amount), "time": "night" if hour < 6 else "morning" if hour < 12 else "afternoon" if hour < 18 else "evening",
        "burst": int((prior["ts"] >= r["ts"] - pd.Timedelta(hours=1)).sum()), "prior": int(len(prior)), "lastPaid": last,
        "usual": None if ok.empty else round(ok["amount_paise"].mean() / 100),
    }


def transaction_detail(ds: MerchantDataset, tid: str) -> dict[str, Any] | None:
    tx = ds.transactions
    m = tx[tx["tid"] == tid]
    if m.empty:
        return None
    r = m.iloc[0]
    row = query_transactions(ds, date_from=None, date_to=None, status=[], outlet=None, risk=None, discrepancy=None, q=tid, sort="ts", desc=False, page=1, page_size=5)["rows"]
    base = next(x for x in row if x["tid"] == tid)
    order = None
    siblings: list[dict[str, Any]] = []
    if r["order_id"] and ds.has_orders and (ds.orders["order_id"] == r["order_id"]).any():
        o = ds.orders[ds.orders["order_id"] == r["order_id"]].iloc[0]
        order = {"order_id": o["order_id"], "ts": o["ts"].isoformat(), "amount_paise": int(o["amount_paise"]), "outlet": o["outlet"]}
    if r["order_id"]:
        siblings = [{"tid": s.tid, "ts": s.ts.isoformat(), "amount_paise": int(s.amount_paise), "status": s.status} for s in tx[(tx["order_id"] == r["order_id"]) & (tx["tid"] != tid)].itertuples()]
    refunds = [{"refund_id": x.refund_id, "ts": x.ts.isoformat(), "amount_paise": int(x.amount_paise)} for x in ds.refunds[ds.refunds["txn_ref"] == r["txn_ref"]].itertuples()]
    disc = [d for d in ds.discrepancies if tid in d["tids"]]
    risk = None
    if ds.risk is not None and tid in ds.risk.index:
        k = ds.risk.loc[tid]
        risk = {
            "level": k["level"], "score": None if pd.isna(k["score"]) else round(float(k["score"]), 1), "signal": k["signal"], "alert": bool(k["alert"]),
            "risk_model": None if pd.isna(k["sup_pct"]) else {"percentile": round(float(k["sup_pct"]), 1), "level": k["sup_level"], "modelled_chance": round(float(k["sup_prob"]), 3), "reasons": list(k["sup_reasons"])},
            "unusual_activity": None if pd.isna(k["an_pct"]) else {"percentile": round(float(k["an_pct"]), 1), "level": k["an_level"], "reasons": list(k["an_reasons"])},
        }
    steps = [d["next_step"] for d in disc]
    if risk and risk["alert"]:
        steps.append("Confirm with the customer or your payment provider that this payment is genuine. The score is a prompt to look, not proof of anything.")
    return {**base, "outlet": r["outlet"], "order": order, "fraud_inputs": fraud_inputs(ds, r), "same_order_payments": siblings, "refunds": refunds, "discrepancy_items": disc, "risk": risk, "recommended_steps": list(dict.fromkeys(steps))}
