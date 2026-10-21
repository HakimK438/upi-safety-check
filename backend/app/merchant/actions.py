"""Action center: one prioritised list of things worth a merchant's attention, each tied to real evidence.

Every item says what KIND of finding it is, so rules, models and gaps are never mixed up:
  rule_based_discrepancy  records that do not add up (reconciliation rules)
  ml_risk_alert           a model ranked this transaction in the top 5% for review
  unusual_activity        a day or payment that is far from this business's own pattern
  observation             information (for example, a missing data source)
None of these is a confirmed fraud or a confirmed loss. Investigation status is kept by the merchant in the browser.
"""

from __future__ import annotations

import math
from typing import Any

from .analytics import unusual_days
from .model import MerchantDataset
from .reconcile import inr

SEV_WEIGHT = {"high": 60, "medium": 40, "low": 20}
MAX_ML_ITEMS = 25


def _amount_points(paise: int) -> float:
    return min(30.0, 8 * math.log10(1 + paise / 10000))  # Rs 100 -> 2.4, Rs 10,000 -> 24, capped at 30


def build_actions(ds: MerchantDataset) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for d in ds.discrepancies:
        items.append({
            "id": d["id"], "kind": "discrepancy", "classification": "rule_based_discrepancy", "title": d["title"], "severity": d["severity"], "ts": d["ts"],
            "summary": d["evidence"][0] if d["evidence"] else d["title"], "amount_at_stake_paise": d["amount_at_stake_paise"], "next_step": d["next_step"],
            "priority": round(SEV_WEIGHT[d["severity"]] + _amount_points(d["amount_at_stake_paise"]), 1), "tids": d["tids"][:5], "order_ids": d["order_ids"][:5], "refund_ids": d["refund_ids"][:5], "refs": d["keys"][:8],
        })
    if ds.risk is not None:
        tx = ds.transactions.set_index("tid")
        top = ds.risk[ds.risk["alert"]].sort_values("score", ascending=False).head(MAX_ML_ITEMS)
        for tid, k in top.iterrows():
            if tid not in tx.index:
                continue
            t = tx.loc[tid]
            reasons = list(k["sup_reasons"] if k["signal"] in ("risk_model", "both") else k["an_reasons"])
            kind = "ml_risk_alert" if k["signal"] in ("risk_model", "both") else "unusual_activity"
            items.append({
                "id": f"risk:{tid}", "kind": "risk", "classification": kind, "severity": k["level"],
                "title": ("Risk model flagged " if kind == "ml_risk_alert" else "Unusual payment: ") + inr(t["amount_paise"]),
                "ts": t["ts"].isoformat(), "summary": "Flagged because " + "; ".join(reasons[:2]) + ".", "amount_at_stake_paise": 0,
                "next_step": "Confirm with the customer or your payment provider that this payment is genuine. The score is a prompt to look, not proof of anything.",
                "priority": round((50 if k["level"] == "high" else 30) + (k["score"] - 95) * 1.0, 1), "tids": [tid], "order_ids": [t["order_id"]] if t["order_id"] else [], "refs": [tid],
            })
    for u in (ds.unusual or unusual_days(ds))[:5]:
        items.append({
            "id": f"day:{u['date']}", "kind": "day", "classification": "unusual_activity", "severity": "medium", "title": f"Unusual {'high' if u['direction'] == 'above' else 'low'} {'sales' if u['metric'] == 'recorded_sales' else 'payments'} on {u['date']}",
            "ts": u["date"], "summary": f"{inr(u['value_paise'])} against a typical {inr(u['typical_paise'])} for recent days.", "amount_at_stake_paise": 0,
            "next_step": "Check whether something explains it (a promotion, a holiday, a closed outlet, a data gap).", "priority": 25.0, "tids": [], "order_ids": [],
        })
    gaps = []
    if not ds.has_orders:
        gaps.append(("no-orders", "Order records not provided", "Without order records, payments cannot be matched to sales, so unmatched orders and payments are not detected.", "Add an orders file (order_id, timestamp, amount) on the Data page."))
    if not ds.has_settlements:
        gaps.append(("no-settlements", "Settlement records not provided", "Without settlement records, confirmed payments cannot be compared with money that reached the bank.", "Add a settlement file (date, amount) on the Data page."))
    if not ds.risk_info.get("supervised", {}).get("available"):
        gaps.append(("no-risk-model", "Risk model not used on this data", ds.risk_info.get("supervised", {}).get("reason", "Not available."), "Only the unusual-activity check is running."))
    for gid, title, summary, step in gaps:
        items.append({"id": f"obs:{gid}", "kind": "observation", "classification": "observation", "severity": "low", "title": title, "ts": ds.anchor.isoformat(), "summary": summary, "amount_at_stake_paise": 0, "next_step": step, "priority": 10.0, "tids": [], "order_ids": []})
    items.sort(key=lambda r: (-r["priority"], r["ts"]))
    return items
