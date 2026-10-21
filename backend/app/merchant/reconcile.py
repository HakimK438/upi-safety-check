"""Reconciliation: compare orders, payments, refunds and settlements and list what does not add up.

Rules only, no ML. Every item is a *discrepancy to verify*, never a verdict of fraud or loss: records can
disagree for ordinary reasons (a missing order id, a settlement delay, a retry). Each item carries the
evidence, a supported explanation if one exists, and the next verification step.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

from .model import MerchantDataset

SEV = ["low", "medium", "high"]
BASE_SEVERITY = {
    "order_without_payment": "medium", "payment_without_order": "medium", "amount_mismatch": "medium", "duplicate_reference": "medium",
    "duplicate_payment": "high", "possible_duplicate_payment": "low", "ambiguous_match": "low", "pending_payment": "low",
    "refund_review": "medium", "reversal_review": "low", "settlement_shortfall": "high", "settlement_excess": "medium",
}
TITLES = {
    "order_without_payment": "Order with no confirmed payment", "payment_without_order": "Payment with no matching order",
    "amount_mismatch": "Order and payment amounts differ", "duplicate_reference": "Same transaction reference recorded more than once",
    "duplicate_payment": "Order paid more than once", "possible_duplicate_payment": "Possible duplicate payment",
    "ambiguous_match": "Payment could belong to more than one order", "pending_payment": "Payment still pending after a day",
    "refund_review": "Refund needs review", "reversal_review": "Reversed payment", "settlement_shortfall": "Settlement lower than expected",
    "settlement_excess": "Settlement higher than expected",
}
PENDING_AFTER = pd.Timedelta(hours=24)
MATCH_WINDOW = pd.Timedelta(minutes=30)
DUP_WINDOW = pd.Timedelta(minutes=10)
SETTLEMENT_TOLERANCE_PAISE = 100  # Rs 1: below this, a difference is rounding, not a finding
SETTLEMENT_LAG = pd.Timedelta(days=2)  # the most recent days are not expected to be settled yet


def inr(paise: int | float) -> str:
    p = int(round(paise))
    sign = "-" if p < 0 else ""
    p = abs(p)
    return f"{sign}₹{p // 100:,}.{p % 100:02d}" if p % 100 else f"{sign}₹{p // 100:,}"


def when(ts: pd.Timestamp) -> str:
    return f"{ts:%d %b %Y, %I:%M %p}".replace(" 0", " ")


def reconcile(ds: MerchantDataset) -> list[dict[str, Any]]:
    tx = ds.transactions
    if tx.empty:
        return []
    anchor = ds.anchor
    big = float(tx.loc[tx["status"] == "success", "amount_paise"].quantile(0.9)) if (tx["status"] == "success").any() else float("inf")
    out: list[dict[str, Any]] = []

    def add(kind: str, key: str, *, tids=(), orders=(), refunds=(), outlet=None, ts, expected=None, recorded=None, stake=0, evidence, explanation=None, next_step, confidence="high"):
        sev = BASE_SEVERITY[kind]
        if stake >= big and sev != "high":
            sev = SEV[SEV.index(sev) + 1]
        diff = None if expected is None or recorded is None else int(recorded - expected)
        out.append({
            "id": f"{kind}:{hashlib.sha1(key.encode()).hexdigest()[:10]}", "type": kind, "title": TITLES[kind], "severity": sev,
            "classification": "rule_based_discrepancy", "confidence": confidence,
            "tids": list(tids), "order_ids": list(orders), "refund_ids": list(refunds), "outlet": outlet, "ts": pd.Timestamp(ts).isoformat(),
            "expected_paise": None if expected is None else int(expected), "recorded_paise": None if recorded is None else int(recorded), "difference_paise": diff,
            "amount_at_stake_paise": int(stake), "evidence": list(evidence), "explanation": explanation, "next_step": next_step,
            "keys": [*tids, *orders, *refunds, key],
        })

    primary = tx[~tx["is_dup_row"]]
    pay = primary.copy()

    # 1. the same reference recorded more than once
    for ref, g in tx[tx["txn_ref"].duplicated(keep=False)].groupby("txn_ref"):
        first = g.iloc[0]
        extra = int(g.iloc[1:].loc[g.iloc[1:]["status"] == "success", "amount_paise"].sum())
        add("duplicate_reference", ref, tids=g["tid"], ts=first["ts"], outlet=first["outlet"], expected=first["amount_paise"], recorded=first["amount_paise"] + extra, stake=extra,
            evidence=[f"{r.tid}: {inr(r.amount_paise)}, {r.status}, {when(r.ts)}" for r in g.itertuples()],
            explanation="The same reference appears in more than one row. This is often an import or sync repeat; it can also be a double entry.",
            next_step="Open your payment provider's statement and confirm how many times this reference was actually credited.")

    # 2. orders <-> payments
    if ds.has_orders:
        orders = ds.orders.set_index("order_id")
        linked = pay[pay["order_id"].notna()]
        succ_by = {k: g for k, g in linked[linked["status"] == "success"].groupby("order_id")}
        fail_by = {k: g for k, g in linked[linked["status"] == "failed"].groupby("order_id")}
        any_by = set(linked["order_id"])
        matched_pay: set[str] = set()
        unlinked_orders: list[str] = []
        for oid, o in orders.iterrows():
            if oid not in any_by:
                unlinked_orders.append(oid)
                continue
            succ, fail = succ_by.get(oid, linked.iloc[0:0]), fail_by.get(oid, linked.iloc[0:0])
            if len(succ) >= 2:
                total = int(succ["amount_paise"].sum())
                add("duplicate_payment", oid, tids=succ["tid"], orders=[oid], outlet=o["outlet"], ts=succ["ts"].iloc[0], expected=o["amount_paise"], recorded=total, stake=max(0, total - int(o["amount_paise"])),
                    evidence=[f"Order {oid}: {inr(o['amount_paise'])}"] + [f"{r.tid}: {inr(r.amount_paise)}, {when(r.ts)}" for r in succ.itertuples()],
                    explanation="Two or more successful payments carry the same order id, so the customer may have been charged twice.",
                    next_step="Confirm both credits in your bank statement; if both arrived, the extra amount may need to be refunded.")
                matched_pay.update(succ["tid"])
            elif len(succ) == 1:
                p = succ.iloc[0]
                matched_pay.add(p["tid"])
                if int(p["amount_paise"]) != int(o["amount_paise"]):
                    add("amount_mismatch", oid, tids=[p["tid"]], orders=[oid], outlet=o["outlet"], ts=p["ts"], expected=o["amount_paise"], recorded=p["amount_paise"], stake=abs(int(p["amount_paise"]) - int(o["amount_paise"])),
                        evidence=[f"Order {oid}: {inr(o['amount_paise'])}", f"Payment {p['tid']}: {inr(p['amount_paise'])}, {when(p['ts'])}"],
                        explanation="Order and payment are linked by order id, but the amounts differ. Causes can include a discount, a keying error or a part-payment; the data cannot say which.",
                        next_step="Check the invoice for this order and whether a discount, tip or partial payment applies.")
            elif len(fail):
                add("order_without_payment", oid, tids=fail["tid"], orders=[oid], outlet=o["outlet"], ts=o["ts"], expected=o["amount_paise"], recorded=0, stake=o["amount_paise"],
                    evidence=[f"Order {oid}: {inr(o['amount_paise'])}, {when(o['ts'])}", f"{len(fail)} payment attempt(s) for this order, all failed"],
                    explanation="The only payment attempts for this order failed. The customer may have paid another way or not paid at all.",
                    next_step="Check whether the goods or service were delivered, and whether the customer paid by another method.")
            # only pending or reversed payments: covered by the pending / reversal checks below, no second flag here

        # orders with no payment carrying their id: look for a lone payment of the same amount at the same outlet nearby in time
        free = pay[(pay["status"] == "success") & ~pay["tid"].isin(matched_pay) & (pay["order_id"].isna() | ~pay["order_id"].isin(orders.index))]
        free_idx = {k: g for k, g in free.groupby(["outlet", "amount_paise"])}
        used: set[str] = set()
        for oid in unlinked_orders:
            o = orders.loc[oid]
            cands = free_idx.get((o["outlet"], o["amount_paise"]))
            cands = cands[((cands["ts"] - o["ts"]).abs() <= MATCH_WINDOW) & ~cands["tid"].isin(used)] if cands is not None else None
            if cands is not None and len(cands) == 1:
                used.add(cands["tid"].iloc[0])  # one clear candidate: accepted as a match by amount and time
                matched_pay.add(cands["tid"].iloc[0])
            elif cands is not None and len(cands) > 1:
                used.update(cands["tid"])  # reported once, as ambiguous; not again as "payment without order"
                add("ambiguous_match", oid, tids=cands["tid"], orders=[oid], outlet=o["outlet"], ts=o["ts"], expected=o["amount_paise"], recorded=o["amount_paise"], stake=0, confidence="low",
                    evidence=[f"Order {oid}: {inr(o['amount_paise'])}, {when(o['ts'])}"] + [f"Candidate {r.tid}: {when(r.ts)}" for r in cands.itertuples()],
                    explanation="Several payments of the same amount fit this order and none carries the order id.",
                    next_step="Decide by hand which payment belongs to this order; add the order id to payments going forward.")
            else:
                add("order_without_payment", oid, orders=[oid], outlet=o["outlet"], ts=o["ts"], expected=o["amount_paise"], recorded=0, stake=o["amount_paise"],
                    evidence=[f"Order {oid}: {inr(o['amount_paise'])}, {when(o['ts'])}", "No payment record carries this order id", "No payment of the same amount at this outlet within 30 minutes"],
                    explanation=None, next_step="Check whether the customer has paid; look in your bank statement for a credit of this amount around this time.")
        for p in free[~free["tid"].isin(used)].itertuples():
            why = f"Order id {p.order_id} is not in your order records" if pd.notna(p.order_id) and p.order_id else "The payment has no order id and no order of the same amount fits"
            add("payment_without_order", p.tid, tids=[p.tid], outlet=p.outlet, ts=p.ts, expected=0, recorded=p.amount_paise, stake=p.amount_paise,
                evidence=[f"{p.tid}: {inr(p.amount_paise)}, {when(p.ts)}", why],
                explanation="Money was recorded as received but no order explains it. It may be a sale that was not entered, a deposit, or a mistaken payment.",
                next_step="Find the sale this payment belongs to, or check with the payer; if it is a mistaken payment, follow your provider's return process.")

    # 3. same payer, outlet and amount twice within minutes, under different references
    succ = pay[(pay["status"] == "success") & pay["payer_ref"].notna()].sort_values("ts")
    if not succ.empty:
        grp = succ.groupby(["payer_ref", "outlet", "amount_paise"])
        prev_ts, prev_tid, prev_oid = grp["ts"].shift(), grp["tid"].shift(), grp["order_id"].shift()
        near = succ[(succ["ts"] - prev_ts <= DUP_WINDOW) & ~((succ["order_id"] == prev_oid) & succ["order_id"].notna())]
        for p in near.itertuples():
            add("possible_duplicate_payment", p.tid, tids=[prev_tid[p.Index], p.tid], outlet=p.outlet, ts=p.ts, expected=p.amount_paise, recorded=2 * p.amount_paise, stake=p.amount_paise, confidence="medium",
                evidence=[f"{prev_tid[p.Index]} and {p.tid}: both {inr(p.amount_paise)} from the same payer at the same outlet", f"{(p.ts - prev_ts[p.Index]).total_seconds() / 60:.0f} minute(s) apart"],
                explanation="Repeat purchases of the same amount do happen; two within minutes can also be an accidental double payment.",
                next_step="Ask the customer, or check whether two separate sales were made.")

    # 4. pending for more than a day
    for p in pay[(pay["status"] == "pending") & (pay["ts"] < anchor - PENDING_AFTER)].itertuples():
        add("pending_payment", p.tid, tids=[p.tid], orders=[p.order_id] if p.order_id else [], outlet=p.outlet, ts=p.ts, expected=p.amount_paise, recorded=0, stake=p.amount_paise,
            evidence=[f"{p.tid}: {inr(p.amount_paise)}, pending since {when(p.ts)}"],
            explanation="A payment normally ends as success or failed soon after it starts. One still pending after a day needs a status check.",
            next_step="Ask your payment provider for the final status of this reference.")

    # 5. reversed payments
    for p in pay[pay["status"] == "reversed"].itertuples():
        add("reversal_review", p.tid, tids=[p.tid], orders=[p.order_id] if p.order_id else [], outlet=p.outlet, ts=p.ts, expected=p.amount_paise, recorded=0, stake=p.amount_paise,
            evidence=[f"{p.tid}: {inr(p.amount_paise)} reversed ({when(p.ts)})"], explanation="A reversal returns the money to the payer. It is not a finding on its own.",
            next_step="Confirm the reversal was intended and the order is handled (re-billed or cancelled).")

    # 6. refunds
    if not ds.refunds.empty:
        first_by_ref = tx.drop_duplicates("txn_ref").set_index("txn_ref")
        for ref, g in ds.refunds.groupby("txn_ref"):
            total, ids = int(g["amount_paise"].sum()), list(g["refund_id"])
            ev = [f"Refund {r.refund_id}: {inr(r.amount_paise)}, {when(r.ts)}" for r in g.itertuples()]
            if ref not in first_by_ref.index:
                add("refund_review", ref + ":" + ids[0], refunds=ids, ts=g["ts"].iloc[0], expected=0, recorded=total, stake=total, evidence=[*ev, f"No payment with reference {ref} in your records"],
                    explanation="The refund points at a payment that is not in your transaction records.", next_step="Find the original payment; check the reference for a typing error.")
                continue
            p = first_by_ref.loc[ref]
            if p["status"] != "success":
                add("refund_review", ref + ":status", tids=[p["tid"]], refunds=ids, outlet=p["outlet"], ts=g["ts"].iloc[0], expected=0, recorded=total, stake=total,
                    evidence=[*ev, f"The original payment {p['tid']} is marked {p['status']}"],
                    explanation="A refund was issued against a payment that was not recorded as successful" + (", so money may have been returned twice." if p["status"] == "reversed" else "."),
                    next_step="Confirm whether the original payment was really received before treating the refund as correct.")
            elif total > int(p["amount_paise"]):
                add("refund_review", ref + ":over", tids=[p["tid"]], refunds=ids, outlet=p["outlet"], ts=g["ts"].iloc[0], expected=p["amount_paise"], recorded=total, stake=total - int(p["amount_paise"]),
                    evidence=[f"Payment {p['tid']}: {inr(p['amount_paise'])}", *ev],
                    explanation="Total refunded is more than the payment" + (" (the same amount appears twice)." if len(g) > 1 else "."),
                    next_step="Check your bank statement for the refunds actually paid out and recover any excess.")

    # 7. settlements
    if ds.has_settlements:
        ok = primary[primary["status"] == "success"]
        exp = ok.groupby(ok["ts"].dt.normalize())["amount_paise"].sum().sub(ds.refunds.groupby(ds.refunds["ts"].dt.normalize())["amount_paise"].sum(), fill_value=0)
        got = ds.settlements.set_index("date")["amount_paise"]
        for d in exp.index.union(got.index):
            if d > anchor - SETTLEMENT_LAG:
                continue
            e, g = int(exp.get(d, 0)), int(got.get(d, 0))
            if e <= 0 and g == 0:
                continue
            diff = g - e
            if abs(diff) <= SETTLEMENT_TOLERANCE_PAISE:
                continue
            kind = "settlement_shortfall" if diff < 0 else "settlement_excess"
            add(kind, d.date().isoformat(), ts=d, expected=e, recorded=g, stake=abs(diff),
                evidence=[f"{d:%d %b %Y}: payments minus refunds = {inr(e)}", f"Settled amount recorded = {inr(g)}"],
                explanation="Settlement can differ for ordinary reasons (fees, holds, a delay). Fees are not modelled here, so a small difference may be a fee." if kind == "settlement_shortfall" else "More was settled than your payments explain; it may include another day or an adjustment.",
                next_step="Compare this day in your bank or settlement report with the payments and refunds listed for the day.")

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda d: (order[d["severity"]], -d["amount_at_stake_paise"], d["ts"]))
    return out
