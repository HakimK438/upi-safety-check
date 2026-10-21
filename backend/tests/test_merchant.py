"""Merchant dashboard tests. Run from backend/:  python -m pytest -q tests/test_merchant.py

No network and no dependence on the public dataset file: hand-built books with known answers, plus the
built-in sample generator. Risk-model tests train a small model on generated data.
"""

from __future__ import annotations

import collections
import os
import re

os.environ["SKIP_OCR_LOAD"] = "1"
os.environ["MERCHANT_WARM"] = "0"
os.environ["DISABLE_RATE_LIMIT"] = "1"
os.environ["UPI_DB"] = ":memory:"

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.merchant import analytics, risk, store
from app.merchant.model import MerchantDataset, UploadError, empty_orders, empty_refunds, empty_settlements, finalize_transactions, parse_dt, parse_transactions, to_paise
from app.merchant.reconcile import reconcile
from app.merchant.sample import _builtin_base, build_sample

T = pd.Timestamp


def tx_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([{"outlet": "A", "payer_ref": None, "order_id": None, **r, "amount_paise": int(round(r["amount"] * 100)), "ts": T(r["ts"])} for r in rows]).drop(columns="amount")
    return finalize_transactions(df)


def frame(rows: list[dict], cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "amount" in df:
        df["amount_paise"] = (df.pop("amount") * 100).round().astype("int64")
    for c in ("ts", "date"):
        if c in df:
            df[c] = pd.to_datetime(df[c])
    return df[cols]


def books() -> MerchantDataset:
    """Known answers: every planted problem here must be found, and nothing else."""
    tx = tx_df([
        {"txn_ref": "P1", "ts": "2024-06-03 10:02", "amount": 500, "status": "success", "order_id": "O1"},
        {"txn_ref": "P1", "ts": "2024-06-03 10:05", "amount": 500, "status": "success", "order_id": "O1"},  # same reference again
        {"txn_ref": "P2", "ts": "2024-06-03 10:32", "amount": 450, "status": "success", "order_id": "O2"},  # order says 500
        {"txn_ref": "P4", "ts": "2024-06-03 12:00", "amount": 300, "status": "success"},  # no order
        {"txn_ref": "P5", "ts": "2024-06-03 13:01", "amount": 200, "status": "failed", "order_id": "O5"},
        {"txn_ref": "P6a", "ts": "2024-06-03 14:01", "amount": 100, "status": "success", "order_id": "O6"},
        {"txn_ref": "P6b", "ts": "2024-06-03 14:02", "amount": 100, "status": "success", "order_id": "O6"},  # same order paid twice
        {"txn_ref": "P7", "ts": "2024-06-01 08:00", "amount": 120, "status": "pending"},
        {"txn_ref": "P8", "ts": "2024-06-10 12:00", "amount": 50, "status": "success", "order_id": "O7"},  # clean, also sets "now"
    ])
    orders = frame([
        {"order_id": "O1", "ts": "2024-06-03 10:00", "amount": 500, "outlet": "A"}, {"order_id": "O2", "ts": "2024-06-03 10:30", "amount": 500, "outlet": "A"},
        {"order_id": "O3", "ts": "2024-06-03 11:00", "amount": 700, "outlet": "A"}, {"order_id": "O5", "ts": "2024-06-03 13:00", "amount": 200, "outlet": "A"},
        {"order_id": "O6", "ts": "2024-06-03 14:00", "amount": 100, "outlet": "A"}, {"order_id": "O7", "ts": "2024-06-10 11:58", "amount": 50, "outlet": "A"},
    ], ["order_id", "ts", "amount_paise", "outlet"])
    refunds = frame([{"refund_id": "R1", "txn_ref": "P1", "ts": "2024-06-04 09:00", "amount": 800}, {"refund_id": "R2", "txn_ref": "NOPE", "ts": "2024-06-04 10:00", "amount": 100}], ["refund_id", "txn_ref", "ts", "amount_paise"])
    settle = frame([{"date": "2024-06-03", "amount": 1400}], ["date", "amount_paise"])  # payments 1450 that day, so 50 short
    return MerchantDataset(transactions=tx, orders=orders, refunds=refunds, settlements=settle, source="test", label="test")


# --------------------------------------------------------------------------- money and validation
def test_money_is_exact_decimal():
    assert to_paise("₹1,234.50") == 123450 and to_paise("Rs. 99") == 9900 and to_paise("10.005") == 1001  # half-up
    assert sum(to_paise(x) for x in ["0.1", "0.2"]) == 30  # floats would give 30.000000000000004 paise worth of drift elsewhere
    assert to_paise("-5") is None and to_paise("0") is None and to_paise("abc") is None and to_paise(None) is None


def test_dates_iso_stay_iso_and_other_formats_are_day_first():
    # regression: dayfirst=True swapped day and month in ISO text (2024-02-06 became 2024-06-02)
    out = parse_dt(pd.Series(["2024-02-06 22:15:31", "2024-04-01", "05/03/2024 10:30", "13-10-2024", "nonsense", None]))
    assert out.iloc[0] == T("2024-02-06 22:15:31") and out.iloc[1] == T("2024-04-01")
    assert out.iloc[2] == T("2024-03-05 10:30") and out.iloc[3] == T("2024-10-13")  # day first
    assert out.iloc[4:].isna().all()


def test_upload_parsing_reports_bad_rows_and_rejects_missing_columns():
    raw = pd.DataFrame({"Transaction ID": ["A1", "A2", "A3", "A4"], "Date Time": ["2024-05-01 10:00", "not a date", "2024-05-02 11:00", "2024-05-03 09:00"],
                        "Amount": ["100", "50", "-4", "75.5"], "Payment Status": ["Successful", "success", "paid", "weird"]})
    tx, notes = parse_transactions(raw)
    assert list(tx["txn_ref"]) == ["A1"] and tx["amount_paise"].iloc[0] == 10000 and tx["status"].iloc[0] == "success"
    assert len(notes) >= 2 and any("status" in n for n in notes)
    with pytest.raises(UploadError, match="missing required"):
        parse_transactions(pd.DataFrame({"id": [1], "amount": [5]}))
    with pytest.raises(UploadError):
        parse_transactions(pd.DataFrame({"txn_ref": ["x"], "timestamp": ["garbage"], "amount": ["1"], "status": ["success"]}))


# --------------------------------------------------------------------------- reconciliation
def found(ds: MerchantDataset) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = collections.defaultdict(list)
    for d in reconcile(ds):
        out[d["type"]].append(d)
    return out


def test_reconciliation_finds_exactly_the_planted_problems():
    f = found(books())
    assert {k: len(v) for k, v in f.items()} == {"amount_mismatch": 1, "order_without_payment": 2, "payment_without_order": 1, "duplicate_reference": 1, "duplicate_payment": 1,
                                                   "pending_payment": 1, "refund_review": 2, "settlement_shortfall": 1}
    m = f["amount_mismatch"][0]
    assert (m["expected_paise"], m["recorded_paise"], m["difference_paise"], m["amount_at_stake_paise"]) == (50000, 45000, -5000, 5000)
    assert {o for d in f["order_without_payment"] for o in d["order_ids"]} == {"O3", "O5"}
    assert f["payment_without_order"][0]["tids"] == ["P4"] and f["payment_without_order"][0]["amount_at_stake_paise"] == 30000
    dp = f["duplicate_payment"][0]
    assert (dp["expected_paise"], dp["recorded_paise"], dp["amount_at_stake_paise"]) == (10000, 20000, 10000)
    assert f["duplicate_reference"][0]["amount_at_stake_paise"] == 50000
    s = f["settlement_shortfall"][0]
    assert (s["expected_paise"], s["recorded_paise"], s["difference_paise"]) == (145000, 140000, -5000)
    over = next(d for d in f["refund_review"] if "P1" in d["tids"] or d["tids"])
    assert over["expected_paise"] == 50000 and over["recorded_paise"] == 80000 and over["amount_at_stake_paise"] == 30000


def test_every_item_has_evidence_next_step_and_never_claims_fraud():
    for d in reconcile(books()):
        assert d["evidence"] and d["next_step"] and d["classification"] == "rule_based_discrepancy"
        assert not re.search(r"\b(fraud|fraudulent|stolen|theft|lost money)\b", " ".join([d["title"], d["explanation"] or "", *d["evidence"], d["next_step"]]), re.I)


def test_order_id_missing_falls_back_to_amount_and_time_but_ambiguity_goes_to_review():
    tx = tx_df([{"txn_ref": "Q1", "ts": "2024-06-03 10:10", "amount": 400, "status": "success"}, {"txn_ref": "Q2", "ts": "2024-06-03 11:05", "amount": 600, "status": "success"}, {"txn_ref": "Q3", "ts": "2024-06-03 11:10", "amount": 600, "status": "success"}])
    orders = frame([{"order_id": "A", "ts": "2024-06-03 10:00", "amount": 400, "outlet": "A"}, {"order_id": "B", "ts": "2024-06-03 11:00", "amount": 600, "outlet": "A"}], ["order_id", "ts", "amount_paise", "outlet"])
    f = found(MerchantDataset(tx, orders, empty_refunds(), empty_settlements(), "test", "t"))
    assert dict((k, len(v)) for k, v in f.items()) == {"ambiguous_match": 1}  # A matched quietly; B is ambiguous; the two payments are not double reported


def test_without_order_records_no_order_findings_are_invented():
    ds = books()
    ds.orders = empty_orders()
    types = set(found(ds))
    assert not types & {"order_without_payment", "payment_without_order", "amount_mismatch", "duplicate_payment", "ambiguous_match"}


def test_reconciliation_recovers_every_planted_problem_in_the_generated_sample():
    ds = build_sample(_builtin_base(), source_note="test")
    keys = {(d["type"], k) for d in reconcile(ds) for k in d["keys"]}
    missed = [x for x in ds.injected if (x["type"], x["key"]) not in keys]
    assert len(ds.injected) > 50 and not missed, missed[:5]


# --------------------------------------------------------------------------- analytics consistency
@pytest.fixture(scope="module")
def sample() -> MerchantDataset:
    ds = build_sample(_builtin_base(), source_note="test")
    ds.discrepancies = reconcile(ds)
    risk.assess(ds, None)
    return ds


def kp(o: dict, key: str):
    return next(k for k in o["kpis"] if k["key"] == key)


def test_kpis_equal_direct_sums_and_the_chart(sample):
    o = analytics.overview(sample, "all")
    prim = sample.transactions[~sample.transactions["is_dup_row"]]
    ok = prim[prim["status"] == "success"]
    assert kp(o, "confirmed_payments")["value"] == int(ok["amount_paise"].sum())
    assert kp(o, "recorded_sales")["value"] == int(sample.orders["amount_paise"].sum())
    assert kp(o, "refunds_total")["value"] == int(sample.refunds["amount_paise"].sum())
    assert kp(o, "success_rate")["value"] == int(round(10000 * len(ok) / len(prim)))
    for g in ("day", "week", "month"):  # the chart over the same range adds up to the KPI
        pts = analytics.series(sample, g, start=prim["ts"].min().normalize())
        assert sum(p["confirmed"] for p in pts) == kp(o, "confirmed_payments")["value"], g
        assert sum(p["recorded_sales"] for p in pts) == kp(o, "recorded_sales")["value"], g


def test_periods_are_relative_to_data_end_and_compare_with_the_previous_period(sample):
    w = analytics.overview(sample, "week")
    a, b, pa, pb = analytics.window(sample, "week")
    assert (b - a).days == 7 and (pb - pa).days == 7 and pb == a
    tx = analytics._in(analytics._primary(sample), "ts", a, b)
    assert kp(w, "confirmed_payments")["value"] == int(tx.loc[tx["status"] == "success", "amount_paise"].sum())
    assert w["data_end"] == sample.anchor.isoformat()


def test_transaction_filters_search_sort_and_pagination_agree(sample):
    base = dict(date_from=None, date_to=None, status=[], outlet=None, risk=None, discrepancy=None, q=None, sort="ts", desc=True, page=1, page_size=10)
    allq = analytics.query_transactions(sample, **base)
    assert allq["total"] == len(sample.transactions) and len(allq["rows"]) == 10
    failed = analytics.query_transactions(sample, **{**base, "status": ["failed"], "page_size": 100})
    assert failed["total"] == int((sample.transactions["status"] == "failed").sum()) and all(r["status"] == "failed" for r in failed["rows"])
    r0 = allq["rows"][0]
    hit = analytics.query_transactions(sample, **{**base, "q": r0["tid"][:8].lower()})
    assert any(r["tid"] == r0["tid"] for r in hit["rows"])
    by_amt = analytics.query_transactions(sample, **{**base, "sort": "amount", "desc": True})["rows"]
    assert [r["amount_paise"] for r in by_amt] == sorted((r["amount_paise"] for r in by_amt), reverse=True)
    p1, p2 = analytics.query_transactions(sample, **{**base, "page": 1}), analytics.query_transactions(sample, **{**base, "page": 2})
    assert not {r["tid"] for r in p1["rows"]} & {r["tid"] for r in p2["rows"]}
    day = sample.anchor.date().isoformat()
    one_day = analytics.query_transactions(sample, **{**base, "date_from": day, "date_to": day, "page_size": 100})
    assert one_day["total"] == int((sample.transactions["ts"].dt.date == sample.anchor.date()).sum())


def test_duplicate_references_get_unique_ids_and_a_detail_view(sample):
    dups = sample.transactions[sample.transactions["is_dup_row"]]
    assert len(dups) and dups["tid"].is_unique and sample.transactions["tid"].is_unique
    d = analytics.transaction_detail(sample, dups["tid"].iloc[0])
    assert d and d["is_duplicate_row"] and any(i["type"] == "duplicate_reference" for i in d["discrepancy_items"]) and d["recommended_steps"]
    assert analytics.transaction_detail(sample, "does-not-exist") is None


def test_single_row_dataset_does_not_break_anything():
    tx = tx_df([{"txn_ref": "Z1", "ts": "2024-01-01 10:00", "amount": 10, "status": "success"}])
    ds = MerchantDataset(tx, empty_orders(), empty_refunds(), empty_settlements(), "test", "t")
    ds.discrepancies = reconcile(ds)
    risk.assess(ds, None)
    assert analytics.overview(ds, "week")["kpis"] and analytics.series(ds, "week") and analytics.unusual_days(ds) == []
    assert ds.risk_info["anomaly"]["available"] is False and ds.risk_info["supervised"]["available"] is False


# --------------------------------------------------------------------------- risk
@pytest.fixture(scope="module")
def trained():
    base = _builtin_base(1800)
    y = base.pop("_fraud").to_numpy()
    tx = finalize_transactions(base.drop(columns=["order_id"]))
    order = tx["ts"].argsort(kind="stable")
    cut = int(len(tx) * 0.75)
    m = risk.train_supervised(tx.iloc[:cut], y[:cut], C=0.5)  # time-ordered split: no shuffling
    m["meta"] = {"model": "test model", "trained_on": "generated data", "split": "time", "metrics": {}, "caveat": "test"}
    return m, tx.iloc[cut:]


def test_training_and_inference_use_the_same_features(trained):
    m, te = trained
    f = risk.sup_features(te)
    assert list(f.columns) == risk.SUP_NUM + risk.SUP_CAT
    prob, why = risk.score_supervised(m, te)
    assert prob.shape == (len(te),) and ((prob >= 0) & (prob <= 1)).all() and all(why)


def test_assess_scores_every_row_with_percentiles_and_reasons(sample, trained):
    m, _ = trained
    ds = build_sample(_builtin_base(), source_note="test")
    risk.assess(ds, m)
    r = ds.risk
    assert len(r) == len(ds.transactions) and ds.risk_info["supervised"]["available"] and ds.risk_info["anomaly"]["available"]
    assert r["score"].between(0, 100).all() and set(r["level"].dropna()) <= {"low", "medium", "high"}
    alerts = r[r["alert"]]
    assert 0.03 < len(alerts) / len(r) < 0.2
    assert all((k["sup_reasons"] if k["signal"] != "unusual_activity" else k["an_reasons"]) for _, k in alerts.iterrows())


def test_risk_degrades_honestly_without_signals_or_without_enough_rows(sample):
    ds = MerchantDataset(sample.transactions.assign(sig_new_device=np.nan, sig_ip_mismatch=np.nan, sig_failed_attempts=np.nan), sample.orders, sample.refunds, sample.settlements, "test", "t")
    risk.assess(ds, {"pipeline": None, "feature_means": None, "meta": {}})  # model present but data lacks signals: must not be used
    assert not ds.risk_info["supervised"]["available"] and "payer-side" in ds.risk_info["supervised"]["reason"] and ds.risk_info["anomaly"]["available"]
    small = MerchantDataset(sample.transactions.head(20), empty_orders(), empty_refunds(), empty_settlements(), "test", "t")
    risk.assess(small, None)
    assert not small.risk_info["anomaly"]["available"] and small.risk["level"].isna().all()


# --------------------------------------------------------------------------- API
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


BANNED = re.compile(r"\b(safe|safely|unsafe|legit|legitimate|confirmed fraud|fraudulent transaction)\b", re.I)


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)


def csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def test_sample_endpoints_and_wording(client):
    paths = ["/meta", "/overview?period=week", "/overview?period=all", "/series?granularity=month", "/transactions?page_size=5", "/reconciliation", "/risk", "/actions"]
    for p in paths:
        r = client.get("/api/merchant/sample" + p)
        assert r.status_code == 200, p
        assert not [s for s in strings(r.json()) if BANNED.search(s)], p
    assert client.get("/api/merchant/datasets/sample").json()["source"] == "sample"
    assert client.get("/api/merchant/sample/overview?period=year").status_code == 422
    assert client.get("/api/merchant/sample/transactions?page_size=500").status_code == 422
    assert client.get("/api/merchant/sample/transactions?date_from=garbage").status_code == 422


def test_reconciliation_can_be_narrowed_to_a_day_and_an_outlet(client):
    allr = client.get("/api/merchant/sample/reconciliation?page_size=100").json()
    day = allr["items"][0]["ts"][:10]
    one = client.get(f"/api/merchant/sample/reconciliation?date_from={day}&date_to={day}&page_size=100").json()
    assert 0 < one["total"] <= allr["total"]
    assert all(d["ts"][:10] == day for d in one["items"])
    assert sum(v["count"] for v in one["summary"].values()) == one["total"]  # summary follows the same scope
    outlet = next(d["outlet"] for d in allr["items"] if d["outlet"])
    by_outlet = client.get(f"/api/merchant/sample/reconciliation?outlet={outlet}&page_size=100").json()
    assert by_outlet["total"] > 0 and all(d["outlet"] == outlet for d in by_outlet["items"])
    assert client.get("/api/merchant/sample/reconciliation?date_from=yesterday").status_code == 422


def test_unknown_dataset_is_404_and_uploads_are_isolated(client):
    assert client.get("/api/merchant/not-a-real-id/overview").status_code == 404
    a = pd.DataFrame({"txn_ref": ["A1", "A2"], "timestamp": ["2024-05-01 10:00", "2024-05-01 11:00"], "amount": [100, 200], "status": ["success", "success"]})
    b = pd.DataFrame({"txn_ref": ["B1"], "timestamp": ["2024-06-01 10:00"], "amount": [999], "status": ["failed"]})
    ra = client.post("/api/merchant/datasets", files={"transactions": ("a.csv", csv(a))})
    rb = client.post("/api/merchant/datasets", files={"transactions": ("b.csv", csv(b))})
    assert ra.status_code == rb.status_code == 201
    ia, ib = ra.json()["id"], rb.json()["id"]
    assert ia != ib and len(ia) > 20
    ta = client.get(f"/api/merchant/{ia}/transactions").json()
    tb = client.get(f"/api/merchant/{ib}/transactions").json()
    assert {r["tid"] for r in ta["rows"]} == {"A1", "A2"} and {r["tid"] for r in tb["rows"]} == {"B1"}
    assert client.get(f"/api/merchant/{ia}/transactions/B1").status_code == 404  # one merchant cannot read another's record
    assert client.delete(f"/api/merchant/datasets/{ia}").status_code == 204 and client.get(f"/api/merchant/{ia}/meta").status_code == 404
    assert client.delete("/api/merchant/datasets/sample").status_code == 404


def test_bad_uploads_are_rejected_with_a_readable_message(client):
    r = client.post("/api/merchant/datasets", files={"transactions": ("x.csv", b"id,amount\n1,5\n")})
    assert r.status_code == 422 and "missing required" in r.json()["detail"]
    r = client.post("/api/merchant/datasets", files={"transactions": ("x.csv", b"txn_ref,timestamp,amount,status\n")})
    assert r.status_code == 422
    r = client.post("/api/merchant/datasets", files={"transactions": ("x.csv", b"\x00\x01garbage")})
    assert r.status_code == 422


def test_exported_sample_can_be_uploaded_back_and_reconciles_the_same(client):
    files = {}
    for t in ("transactions", "orders", "refunds", "settlements"):
        r = client.get(f"/api/merchant/sample/export/{t}.csv")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        files[t] = (f"{t}.csv", r.content)
    up = client.post("/api/merchant/datasets", files=files)
    assert up.status_code == 201, up.text
    got = up.json()["discrepancy_counts"]["by_type"]
    want = client.get("/api/merchant/sample/meta").json()["discrepancy_counts"]["by_type"]
    assert {k: v["count"] for k, v in got.items()} == {k: v["count"] for k, v in want.items()}
    ov_s, ov_u = client.get("/api/merchant/sample/overview?period=all").json(), client.get(f"/api/merchant/{up.json()['id']}/overview?period=all").json()
    for key in ("recorded_sales", "confirmed_payments", "refunds_total", "settled"):
        assert kp(ov_s, key)["value"] == kp(ov_u, key)["value"], key
    client.delete(f"/api/merchant/datasets/{up.json()['id']}")


def test_action_items_are_classified_and_linked_to_evidence(client):
    items = client.get("/api/merchant/sample/actions?limit=200").json()["items"]
    assert items and items == sorted(items, key=lambda a: (-a["priority"], a["ts"]))
    assert {a["classification"] for a in items} <= {"rule_based_discrepancy", "ml_risk_alert", "unusual_activity", "observation"}
    for a in items:
        if a["kind"] in ("discrepancy", "risk"):
            assert a["refs"], a["id"]
        assert a["next_step"] and a["summary"]


def test_table_preview_endpoint_pages_the_raw_tables(client):
    for name, n in (("orders", len(store.get_sample().orders)), ("refunds", len(store.get_sample().refunds)), ("settlements", len(store.get_sample().settlements))):
        r = client.get(f"/api/merchant/sample/table/{name}?page_size=3")
        assert r.status_code == 200 and r.json()["total"] == n and len(r.json()["rows"]) == min(3, n) and r.json()["columns"]
    assert client.get("/api/merchant/sample/table/secrets").status_code == 422
    assert client.get("/api/merchant/nope/table/orders").status_code == 404
