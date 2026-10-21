"""/api/merchant/*: read-only analytics over an in-memory dataset ('sample' or an uploaded one)."""

from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import analytics, dashboard, explore, spam_lab, store
from .model import MerchantDataset, UploadError
from .reconcile import BASE_SEVERITY, TITLES

router = APIRouter(prefix="/api/merchant", tags=["merchant"])
LABELS_DIR = Path(__file__).resolve().parents[2] / "data" / "review_labels"  # git-ignored; read by the next retrain

Period = Literal["day", "week", "month", "all"]


def _ds(ds_id: str) -> MerchantDataset:
    ds = store.get(ds_id)
    if ds is None:
        raise HTTPException(404, "That dataset was not found or has expired. Reload the sample or upload your files again.")
    return ds


def _meta(ds_id: str, ds: MerchantDataset) -> dict[str, Any]:
    tx = ds.transactions
    by_type = collections.Counter(d["type"] for d in ds.discrepancies)
    by_sev = collections.Counter(d["severity"] for d in ds.discrepancies)
    sup = ds.risk_info.get("supervised", {})
    return {
        "id": ds_id, "label": ds.label, "source": ds.source, "notes": ds.notes, "warnings": ds.warnings,
        "data_start": tx["ts"].min().isoformat(), "data_end": ds.anchor.isoformat(),
        "counts": {"transactions": int((~tx["is_dup_row"]).sum()), "duplicate_rows": int(tx["is_dup_row"].sum()), "orders": len(ds.orders), "refunds": len(ds.refunds), "settlement_days": len(ds.settlements), "outlets": int(tx["outlet"].nunique())},
        "capabilities": {"orders": ds.has_orders, "settlements": ds.has_settlements, "risk_model": bool(sup.get("available")), "unusual_activity": bool(ds.risk_info.get("anomaly", {}).get("available"))},
        "risk_info": ds.risk_info, "discrepancy_counts": {"total": len(ds.discrepancies), "by_type": {k: {"count": v, "title": TITLES[k], "default_severity": BASE_SEVERITY[k]} for k, v in by_type.items()}, "by_severity": dict(by_sev)},
        "definitions": analytics.DEFINITIONS, "outlets": sorted(tx["outlet"].unique().tolist()),
        "retention": "Held in memory only; discarded after 2 hours or when the server restarts." if ds.source == "upload" else "Sample data is regenerated on every server start.",
    }


@router.get("/datasets/sample")
def sample() -> dict[str, Any]:
    return _meta("sample", store.get_sample())


@router.post("/datasets", status_code=201)
async def upload(
    transactions: Annotated[UploadFile, File(description="CSV with txn_ref, timestamp, amount, status (optional: order_id, outlet, payer_ref)")],
    orders: UploadFile | None = None, refunds: UploadFile | None = None, settlements: UploadFile | None = None,
) -> dict[str, Any]:
    async def body(f: UploadFile | None) -> bytes | None:
        return await f.read() if f is not None and f.filename else None

    try:
        ds_id, ds = store.create_upload(await transactions.read(), await body(orders), await body(refunds), await body(settlements))
    except UploadError as e:
        raise HTTPException(422, str(e)) from e
    return _meta(ds_id, ds)


@router.delete("/datasets/{ds_id}", status_code=204, response_class=Response, response_model=None)
def remove(ds_id: str) -> None:
    if ds_id == "sample" or not store.delete(ds_id):
        raise HTTPException(404, "That dataset was not found.")


@router.get("/{ds_id}/meta")
def meta(ds_id: str) -> dict[str, Any]:
    return _meta(ds_id, _ds(ds_id))


@router.get("/{ds_id}/overview")
def overview(ds_id: str, period: Period = "week") -> dict[str, Any]:
    return analytics.overview(_ds(ds_id), period)


@router.get("/{ds_id}/dashboard")
def dashboard_report(
    ds_id: str, date_from: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None, date_to: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    branch: Annotated[str | None, Query(max_length=60)] = None, status: Literal["success", "failed", "pending", "reversed"] | None = None,
    zone: Literal["safe", "check", "fraud"] | None = None, hour: Annotated[int | None, Query(ge=0, le=23)] = None, dow: Annotated[int | None, Query(ge=0, le=6)] = None,
    day: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
) -> dict[str, Any]:
    return dashboard.build(_ds(ds_id), date_from=date_from, date_to=date_to, branch=branch, status=status, zone=zone, hour=hour, dow=dow, day=day)


@router.get("/{ds_id}/series")
def series(ds_id: str, granularity: Literal["day", "week", "month"] = "day", days: Annotated[int | None, Query(ge=7, le=3650)] = None) -> dict[str, Any]:
    ds = _ds(ds_id)
    start = None if days is None else ds.anchor.normalize() + pd.Timedelta(days=1) - pd.Timedelta(days=days)
    return {"granularity": granularity, "points": analytics.series(ds, granularity, start=start)}


@router.get("/{ds_id}/transactions")
def transactions(
    ds_id: str, date_from: str | None = None, date_to: str | None = None, status: Annotated[list[Literal["success", "failed", "pending", "reversed"]] | None, Query()] = None,
    outlet: str | None = None, risk: Literal["alerts", "high", "medium", "low"] | None = None, discrepancy: bool | None = None, q: Annotated[str | None, Query(max_length=60)] = None,
    sort: Literal["ts", "amount", "risk"] = "ts", desc: bool = True, page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    tab: Literal["all", "received", "refunded", "not_received", "risky"] | None = None,
) -> dict[str, Any]:
    try:
        for d in (date_from, date_to):
            if d:
                pd.Timestamp(d)
    except ValueError as e:
        raise HTTPException(422, "Dates must look like 2024-12-31.") from e
    return analytics.query_transactions(_ds(ds_id), date_from=date_from, date_to=date_to, status=list(status or []), outlet=outlet, risk=risk, discrepancy=discrepancy, q=q, sort=sort, desc=desc, page=page, page_size=page_size, tab=tab)


@router.get("/{ds_id}/transactions.csv")
def transactions_csv(
    ds_id: str, date_from: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None, date_to: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    outlet: str | None = None, q: Annotated[str | None, Query(max_length=60)] = None, tab: Literal["all", "received", "refunded", "not_received", "risky"] | None = None,
) -> Response:
    """The payments in the current view (same filters as the table) as a CSV file."""
    rows = analytics.query_transactions(_ds(ds_id), date_from=date_from, date_to=date_to, status=[], outlet=outlet, risk=None, discrepancy=None, q=q, sort="ts", desc=True, page=1, page_size=50_000, tab=tab)["rows"]
    f = pd.DataFrame([{"reference": r["tid"], "time": r["ts"], "amount": f"{r['amount_paise'] / 100:.2f}", "status": r["status"], "branch": r["outlet"].replace("Outlet", "Branch"),
                       "customer": r["payer"], "refunded": f"{r['refund_paise'] / 100:.2f}", "risk": r["risk_level"] or ""} for r in rows])
    return Response(f.to_csv(index=False), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="payments.csv"'})


@router.get("/{ds_id}/transactions/{tid:path}")
def transaction(ds_id: str, tid: str) -> dict[str, Any]:
    d = analytics.transaction_detail(_ds(ds_id), tid)
    if d is None:
        raise HTTPException(404, "No such transaction in this dataset.")
    return d


@router.get("/{ds_id}/reconciliation")
def reconciliation(
    ds_id: str, type: str | None = None, severity: Literal["high", "medium", "low"] | None = None, outlet: str | None = None,
    date_from: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None, date_to: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    """Discrepancies, optionally narrowed to one kind, outlet or date range (dates inclusive, e.g. 2024-12-04)."""
    ds = _ds(ds_id)
    lo = date_from or "0000-01-01"
    hi = (date_to or "9999-12-31") + "T23:59:59.999999"  # `ts` is an ISO string, so string comparison orders correctly
    scoped = [d for d in ds.discrepancies if (not outlet or d["outlet"] == outlet) and lo <= d["ts"] <= hi]
    rows = [d for d in ds.discrepancies if (not type or d["type"] == type) and (not severity or d["severity"] == severity) and (not outlet or d["outlet"] == outlet) and lo <= d["ts"] <= hi]
    return {
        "total": len(rows), "page": page, "page_size": page_size, "items": rows[(page - 1) * page_size: page * page_size],
        "matching": {"orders_checked": len(ds.orders), "payments_checked": int((~ds.transactions["is_dup_row"]).sum()), "refunds_checked": len(ds.refunds), "settlement_days_checked": len(ds.settlements),
                     "order_matching_ran": ds.has_orders, "settlement_check_ran": ds.has_settlements},
        "summary": {k: {"count": v, "title": TITLES[k], "amount_at_stake_paise": int(sum(d["amount_at_stake_paise"] for d in scoped if d["type"] == k))} for k, v in collections.Counter(d["type"] for d in scoped).items()},
    }


@router.get("/{ds_id}/risk")
def risk_alerts(
    ds_id: str, level: Literal["high", "medium"] | None = None, page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    date_from: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None, date_to: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    outlet: str | None = None,
) -> dict[str, Any]:
    """Flagged payments (zone Check or Fraud), most likely fraud first, each with its plain reasons and the Fraud check inputs."""
    ds = _ds(ds_id)
    r = ds.risk
    out: list[dict[str, Any]] = []
    total = 0
    zones = {"safe": 0, "check": 0, "fraud": 0}
    if r is not None:
        tx = ds.transactions.set_index("tid")
        scope = tx[~tx["is_dup_row"]]
        if date_from:
            scope = scope[scope["ts"] >= pd.Timestamp(date_from)]
        if date_to:
            scope = scope[scope["ts"] < pd.Timestamp(date_to) + pd.Timedelta(days=1)]
        if outlet:
            scope = scope[scope["outlet"] == outlet]
        lv = r.loc[r.index.intersection(scope.index), "level"]
        zones = {"safe": int((lv == "low").sum()), "check": int((lv == "medium").sum()), "fraud": int((lv == "high").sum())}
        a = r.loc[lv.index][(r.loc[lv.index, "alert"]) & ((r.loc[lv.index, "level"] == level) if level else True)].sort_values("score", ascending=False)
        total = len(a)
        for tid, k in a.iloc[(page - 1) * page_size: page * page_size].iterrows():
            t = tx.loc[tid]
            row = t.copy()
            row["tid"] = tid
            out.append({"tid": tid, "ts": t["ts"].isoformat(), "amount_paise": int(t["amount_paise"]), "status": t["status"], "outlet": t["outlet"], "level": k["level"], "score": round(float(k["score"]), 1),
                        "chance": None if pd.isna(k["sup_prob"]) else round(float(k["sup_prob"]), 3), "reasons": list(k["sup_reasons"])[:3], "fraud_inputs": analytics.fraud_inputs(ds, row)})
    return {"total": total, "zones": zones, "page": page, "page_size": page_size, "items": out, "info": ds.risk_info}


def _labels_file(ds_id: str):
    return LABELS_DIR / f"{ds_id}.json"


@router.get("/{ds_id}/labels")
def get_labels(ds_id: str) -> dict[str, str]:
    """Fraud / Fine marks the merchant gave to flagged payments. Kept for the next model retrain."""
    _ds(ds_id)
    f = _labels_file(ds_id)
    return json.loads(f.read_text()) if f.exists() else {}


class LabelIn(BaseModel):
    tid: str = Field(max_length=60)
    label: Literal["fraud", "fine"] | None


@router.post("/{ds_id}/labels")
def set_label(ds_id: str, body: LabelIn) -> dict[str, str]:
    ds = _ds(ds_id)
    if not (ds.transactions["tid"] == body.tid).any():
        raise HTTPException(404, "No such payment in this dataset.")
    cur = get_labels(ds_id)
    if body.label is None:
        cur.pop(body.tid, None)
    else:
        cur[body.tid] = body.label
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    _labels_file(ds_id).write_text(json.dumps(cur))
    return cur


@router.get("/{ds_id}/actions")
def action_center(ds_id: str, kind: Literal["discrepancy", "risk", "day", "observation"] | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict[str, Any]:
    items = [a for a in _ds(ds_id).actions if not kind or a["kind"] == kind]
    return {"total": len(items), "items": items[:limit], "classifications": {
        "rule_based_discrepancy": "Records that do not add up (rules).", "ml_risk_alert": "Ranked in the top 5% for review by a model.",
        "unusual_activity": "Far from this business's own pattern.", "observation": "Information, not a finding.",
    }}


class SpamIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


@router.get("/spam/models")
def spam_models() -> dict[str, Any]:
    """Compare the three NLP spam classifiers (trained on first call)."""
    return spam_lab.summary()


@router.post("/spam/predict")
def spam_predict(body: SpamIn, model: str | None = None) -> dict[str, Any]:
    return spam_lab.predict(body.text, model)


@router.get("/{ds_id}/explore/table")
def explore_table(ds_id: str, name: Literal["payments", "orders", "refunds", "settlements"] = "payments", q: Annotated[str | None, Query(max_length=60)] = None, sort: Annotated[str | None, Query(max_length=30)] = None,
                  desc: bool = False, page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 10) -> dict[str, Any]:
    """Data explorer table: sortable, searchable, with a column type and the share of empty cells for every column."""
    return explore.table_view(_ds(ds_id), name, q, sort, desc, page, page_size)


@router.get("/{ds_id}/explore/eda")
def explore_eda(ds_id: str) -> dict[str, Any]:
    return explore.eda(_ds(ds_id))


@router.get("/{ds_id}/table/{name}")
def table(ds_id: str, name: Literal["orders", "refunds", "settlements"], page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20) -> dict[str, Any]:
    """Browse the raw tables behind the dashboard (the transactions table has its own, richer endpoint)."""
    df = {"orders": _ds(ds_id).orders, "refunds": _ds(ds_id).refunds, "settlements": _ds(ds_id).settlements}[name]
    part = df.iloc[(page - 1) * page_size: page * page_size].copy()
    for c in part.columns:
        if str(part[c].dtype).startswith("datetime"):
            part[c] = part[c].dt.strftime("%Y-%m-%d %H:%M")
    return {"name": name, "total": len(df), "page": page, "page_size": page_size, "columns": list(part.columns), "rows": part.astype(object).where(part.notna(), None).to_dict("records")}


@router.get("/sample/export/{table}.csv")
def export_sample(table: Literal["transactions", "orders", "refunds", "settlements"]) -> Response:
    """The sample as CSV, so you can see the upload format and try your own edits."""
    ds = store.get_sample()
    if table == "transactions":
        t = ds.transactions.copy()
        f = pd.DataFrame({"txn_ref": t["txn_ref"], "timestamp": t["ts"].dt.strftime("%Y-%m-%d %H:%M:%S"), "amount": (t["amount_paise"] / 100).map("{:.2f}".format), "status": t["status"], "order_id": t["order_id"], "outlet": t["outlet"], "payer_ref": t["payer_ref"]})
    elif table == "orders":
        o = ds.orders
        f = pd.DataFrame({"order_id": o["order_id"], "timestamp": o["ts"].dt.strftime("%Y-%m-%d %H:%M:%S"), "amount": (o["amount_paise"] / 100).map("{:.2f}".format), "outlet": o["outlet"]})
    elif table == "refunds":
        r = ds.refunds
        f = pd.DataFrame({"refund_id": r["refund_id"], "txn_ref": r["txn_ref"], "timestamp": r["ts"].dt.strftime("%Y-%m-%d %H:%M:%S"), "amount": (r["amount_paise"] / 100).map("{:.2f}".format)})
    else:
        s = ds.settlements
        f = pd.DataFrame({"date": s["date"].dt.strftime("%Y-%m-%d"), "amount": (s["amount_paise"] / 100).map("{:.2f}".format)})
    return Response(f.to_csv(index=False), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="sample_{table}.csv"'})
