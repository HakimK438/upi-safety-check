"""Data explorer: a browsable view of the four tables and the exploratory charts behind the My data page."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .model import MerchantDataset

TABLES = ("payments", "orders", "refunds", "settlements")
AMOUNT_EDGES = [0, 500, 1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 1e12]
AMOUNT_LABELS = ["under 500", "500 to 1k", "1k to 2.5k", "2.5k to 5k", "5k to 10k", "10k to 25k", "25k to 50k", "50k+"]
PERIODS = [("Night (12-6 am)", 0, 6), ("Morning (6 am-12)", 6, 12), ("Afternoon (12-6 pm)", 12, 18), ("Evening (6 pm-12)", 18, 24)]


def _payments(ds: MerchantDataset) -> pd.DataFrame:
    tx = ds.transactions[~ds.transactions["is_dup_row"]]
    f = pd.DataFrame({"reference": tx["txn_ref"], "time": tx["ts"], "amount": (tx["amount_paise"] / 100).round(2), "status": tx["status"], "branch": tx["outlet"].str.replace("Outlet", "Branch", regex=False),
                      "customer": tx["payer_ref"], "order": tx["order_id"]})
    if "zone" in tx:
        f["risk"] = tx["zone"].map({"safe": "Safe", "check": "Check", "fraud": "Fraud"})
    return f.reset_index(drop=True)


def _frame(ds: MerchantDataset, name: str) -> pd.DataFrame:
    if name == "payments":
        return _payments(ds)
    if name == "orders":
        o = ds.orders
        return pd.DataFrame({"order": o["order_id"], "time": o["ts"], "amount": (o["amount_paise"] / 100).round(2), "branch": o["outlet"].str.replace("Outlet", "Branch", regex=False)}) if len(o) else pd.DataFrame(columns=["order", "time", "amount", "branch"])
    if name == "refunds":
        r = ds.refunds
        return pd.DataFrame({"refund": r["refund_id"], "reference": r["txn_ref"], "time": r["ts"], "amount": (r["amount_paise"] / 100).round(2)}) if len(r) else pd.DataFrame(columns=["refund", "reference", "time", "amount"])
    s = ds.settlements
    return pd.DataFrame({"date": s["date"], "amount": (s["amount_paise"] / 100).round(2)}) if len(s) else pd.DataFrame(columns=["date", "amount"])


def _kind(s: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    return "number" if pd.api.types.is_numeric_dtype(s) else "text"


def table_view(ds: MerchantDataset, name: str, q: str | None, sort: str | None, desc: bool, page: int, page_size: int) -> dict[str, Any]:
    f = _frame(ds, name)
    cols = [{"name": c, "kind": _kind(f[c]), "missing": round(float(f[c].isna().mean()), 4) if len(f) else 0.0} for c in f.columns]  # share of empty cells, whole table
    if q:
        needle = q.strip().lower()
        text = f.astype(str).apply(lambda s: s.str.lower().str.contains(needle, regex=False))
        f = f[text.any(axis=1)]
    if sort in f.columns:
        f = f.sort_values(sort, ascending=not desc, kind="stable", na_position="last")
    part = f.iloc[(page - 1) * page_size: page * page_size].copy()
    for c in part.columns:
        if pd.api.types.is_datetime64_any_dtype(part[c]):
            part[c] = part[c].dt.strftime("%Y-%m-%d %H:%M" if name != "settlements" else "%Y-%m-%d")
    return {"name": name, "total": len(f), "page": page, "page_size": page_size, "columns": cols, "rows": part.astype(object).where(part.notna(), None).to_dict("records")}


def eda(ds: MerchantDataset) -> dict[str, Any]:
    """Seven small summaries, each with the numbers a chart needs and a plain takeaway the page shows as its title."""
    p = _payments(ds)
    hour, dow = p["time"].dt.hour, p["time"].dt.dayofweek
    flagged = (p["risk"] != "Safe") if "risk" in p else pd.Series(False, index=p.index)

    band = pd.cut(p["amount"], AMOUNT_EDGES, labels=AMOUNT_LABELS, right=False)
    amount = [{"band": b, "count": int((band == b).sum())} for b in AMOUNT_LABELS]
    by_hour = [{"hour": h, "count": int((hour == h).sum())} for h in range(24)]
    status = [{"status": s, "count": int(n)} for s, n in p["status"].value_counts().items()]
    missing = [{"column": c, "missing": round(float(p[c].isna().mean()), 4)} for c in p.columns]
    daily = p.groupby(p["time"].dt.normalize()).agg(count=("amount", "size"), amount=("amount", "sum")).reset_index()
    trend = [{"date": r.time.date().isoformat(), "count": int(r["count"]), "amount": round(float(r.amount), 2)} for _, r in daily.iterrows()]

    num = pd.DataFrame({"Amount": p["amount"].to_numpy(), "Hour": hour.to_numpy(), "Weekday": dow.to_numpy(), "Failed": (p["status"] == "failed").astype(int).to_numpy(),
                        "Looks risky": flagged.astype(int).to_numpy()})
    corr = num.corr().fillna(0).round(2)

    def rate(mask: pd.Series) -> float:
        return round(float(flagged[mask].mean()), 4) if mask.any() else 0.0

    factors = [{"factor": f"Amount {b}", "rate": rate(band == b), "count": int((band == b).sum())} for b in AMOUNT_LABELS]
    factors += [{"factor": name, "rate": rate((hour >= a) & (hour < z)), "count": int(((hour >= a) & (hour < z)).sum())} for name, a, z in PERIODS]
    factors += [{"factor": f"Status {s}", "rate": rate(p["status"] == s), "count": int((p["status"] == s).sum())} for s in ("success", "failed", "pending", "reversed")]
    return {"payments": len(p), "amount": amount, "by_hour": by_hour, "status": status, "missing": missing, "trend": trend, "corr": {"labels": list(corr.columns), "matrix": corr.to_numpy().tolist()},
            "factors": factors, "base_rate": round(float(flagged.mean()), 4)}
