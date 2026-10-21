"""/api/fraud: needs the trained models (python ml/train_fraud.py); skipped when they are absent."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.merchant import fraud_api

pytestmark = pytest.mark.skipif(not (fraud_api.MODEL_PATH.exists() and fraud_api.RESULTS_PATH.exists()), reason="fraud models not trained")
client = TestClient(app)


def test_overview_has_all_models_and_triage() -> None:
    o = client.get("/api/fraud/overview").json()
    assert set(o["ieee"]["models"]) >= {"logreg", "rf", "xgb", "mlp"}
    t = o["ieee"]["triage"]
    assert t["check_threshold"] <= t["block_threshold"]
    assert abs(t["block"]["share"] + t["check"]["share"] + t["approve"]["share"] - 1) < 1e-6


def test_score_returns_every_model_and_a_zone() -> None:
    r = client.post("/api/fraud/score", json={"amount": 120, "hour": 14, "customer_prior_payments": 5, "customer_usual_amount": 100})
    assert r.status_code == 200
    out = r.json()
    assert out["band"] in {"low", "medium", "high"}
    assert set(out["models"]) == {"logreg", "rf", "xgb", "mlp"}
    assert 0 <= out["probability"] <= 1


def test_real_test_examples_score_without_errors() -> None:
    ex = client.get("/api/fraud/overview").json()["ieee"]["examples"]
    for x in ex:
        body = {k: v for k, v in x["inputs"].items() if v is not None}
        assert client.post("/api/fraud/score", json=body).status_code == 200


def test_bad_input_is_rejected() -> None:
    assert client.post("/api/fraud/score", json={"amount": -5}).status_code == 422


def test_synthetic_results_carry_eda_and_real_check() -> None:
    o = client.get("/api/fraud/overview").json()
    if not o.get("synthetic"):
        pytest.skip("real-data run")
    assert {p["pattern"] for p in o["eda"]["patterns"]} >= {"account_takeover", "card_testing", "mule_ring"}
    assert o["real_check"] is not None
