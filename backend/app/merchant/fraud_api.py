"""/api/fraud/*: score one payment with every trained model, and serve the stored evaluation.

The models are trained by ml/train_fraud.py (default: SYNTHETIC data in the IEEE-CIS layout; real-data results kept as a side check). Nothing here calls the network.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import fraud_features as ff

ROOT = Path(__file__).resolve().parents[3]
MODEL_PATH = ROOT / "backend" / "models" / "fraud_models.joblib"
RESULTS_PATH = ROOT / "docs" / "ml" / "fraud_results.json"

router = APIRouter(prefix="/api/fraud", tags=["fraud"])


class PaymentIn(BaseModel):
    """What a payment app / gateway knows about one payment. Anything left out is treated as typical."""

    amount: float = Field(gt=0, le=1_000_000)
    hour: int = Field(12, ge=0, le=23)
    product: str = "W"
    network: str = "visa"
    instrument: str = "debit"
    email_domain: str | None = "gmail.com"
    device_type: str = "mobile"
    os: str = "Android"
    browser: str = "Chrome"
    distance_km: float | None = None
    account_age_days: float | None = None
    customer_prior_payments: int = Field(0, ge=0, le=100_000)
    customer_usual_amount: float | None = Field(None, gt=0)
    hours_since_last_payment: float | None = Field(None, ge=0)
    payments_last_hour: int = Field(0, ge=0, le=1000)
    payments_last_24h: int = Field(0, ge=0, le=1000)
    new_device: bool = False
    devices_seen: int = Field(1, ge=0, le=1000)
    accounts_on_device_7d: int = Field(0, ge=0, le=1000)
    prior_fraud: int = Field(0, ge=0, le=100)
    threshold_preset: str = "balanced"


@lru_cache(maxsize=1)
def _bundle() -> dict[str, Any]:
    if not MODEL_PATH.exists():
        raise HTTPException(503, "The fraud models are not trained yet. Run: cd backend && python ml/train_fraud.py")
    return joblib.load(MODEL_PATH)


@lru_cache(maxsize=1)
def _results() -> dict[str, Any]:
    if not RESULTS_PATH.exists():
        raise HTTPException(503, "No evaluation results yet. Run: cd backend && python ml/train_fraud.py")
    return json.loads(RESULTS_PATH.read_text())


def _contrib(model: Any, X: pd.DataFrame, num: list[str], cat: list[str]) -> dict[str, float]:
    """SHAP values (log-odds, + pushes toward fraud) for one row, folded back to the original inputs."""
    pipe = model["pipeline"]
    Z = pipe["pre"].transform(X[num + cat])
    names = list(pipe["pre"].get_feature_names_out())
    m = pipe["m"]
    if hasattr(m, "booster_"):
        c = m.booster_.predict(Z, pred_contrib=True)[0][:-1]
    else:
        import xgboost as xgb
        c = m.get_booster().predict(xgb.DMatrix(Z), pred_contribs=True)[0][:-1]
    out: dict[str, float] = {}
    for j, nm in enumerate(names):
        base = nm.split("__", 1)[-1].removeprefix("missingindicator_")
        col = base if base in num + cat else next((k for k in cat if base.startswith(k + "_")), None)
        if col:
            out[col] = out.get(col, 0.0) + float(c[j])
    return out


def _cuts(presets: dict[str, float]) -> tuple[float, float]:
    """(check, block) cut-offs: the 3-zone triage chosen on validation (block: >=90% precision; block+check: >=90% recall)."""
    t = _results()["ieee"].get("triage")
    return (t["check_threshold"], t["block_threshold"]) if t else (presets["catch_more"], presets["balanced"])


def _band(p: float, presets: dict[str, float]) -> str:
    check, block = _cuts(presets)
    return "high" if p >= block else "medium" if p >= check else "low"


def _advice(band: str) -> str:
    return {"high": "Stop: do not hand over goods or service. Wait until the money shows in your bank account, or ask for another way to pay.",
            "medium": "Looks a little unusual. Check that the payment has really reached your account before you finish the sale.",
            "low": "Nothing unusual stands out. Complete the sale as usual, and still confirm the money in your account for large amounts."}[band]


@router.get("/overview")
def overview() -> dict[str, Any]:
    """Everything the Fraud Check page shows: results of every model, charts data, data insights, example payments."""
    return _results()


@router.post("/score")
def score(p: PaymentIn) -> dict[str, Any]:
    b = _bundle()
    meta, num, cat = b["meta"], b["num"], b["cat"]
    X = ff.from_inputs(p.model_dump())
    for c in num + cat:
        if c not in X:
            X[c] = np.nan
    presets = meta["presets"]
    if p.threshold_preset not in presets:
        raise HTTPException(422, f"threshold_preset must be one of {list(presets)}")
    models: dict[str, Any] = {}
    for mid, m in b["models"].items():
        raw = float(m["pipeline"].predict_proba(X[num + cat])[0, 1])
        prob = float(m["calibrator"].predict([raw])[0])
        models[mid] = {"probability": round(prob, 4), "flagged": prob >= presets[p.threshold_preset]}
    best = meta["best"]
    prob = models[best]["probability"]
    band = _band(prob, presets)
    res = _results()
    rule_hits = [ff.LABELS[f] for f in ff.FLAGS if float(X.iloc[0][f]) > 0]

    reasons_up: list[dict[str, Any]] = []
    reasons_down: list[dict[str, Any]] = []
    if meta["explainer"] in b["models"]:
        con = _contrib(b["models"][meta["explainer"]], X, num, cat)
        vague = {"card4", "card6", "ProductCD", "email", "os", "browser", "DeviceType", "log_amt", "cents", "hour", "uid_gap_h", "has_device_info"}
        ups = []
        for k, v in sorted(con.items(), key=lambda kv: -abs(kv[1]))[:12]:
            item = {"feature": k, "effect": round(v, 3)}
            if v > 0.05 and k in ff.REASON_UP:
                ups.append({**item, "text": ff.REASON_UP[k]})
            elif v < -0.05:
                reasons_down.append({**item, "text": f"Reassuring: {ff.LABELS.get(k, k)}"})
        # specific reasons first (new device, burst, shared device...); vague "pattern" ones only to fill the list
        reasons_up = [r for r in ups if r["feature"] not in vague] + [r for r in ups if r["feature"] in vague]
    base = res["ieee"]["base_rate_test"]
    return {
        "probability": prob, "percent": round(prob * 100, 1), "band": band, "flagged": models[best]["flagged"],
        "headline": {"high": f"Block: very likely fraud. About {round(prob * 100)}% of payments that look like this were fraud.",
                     "medium": f"Check before you hand over goods: about {round(prob * 100)}% of similar payments were fraud.",
                     "low": f"Approve: no strong warning signs. about {round(prob * 100, 1)}% of similar payments were fraud (a typical payment: {round(base * 100, 1)}%)."}[band],
        "advice": _advice(band), "typical_rate_percent": round(base * 100, 2),
        "times_more_than_typical": round(prob / base, 1) if base else None,
        "reasons_up": reasons_up[:4], "reasons_down": reasons_down[:2], "warning_signs": rule_hits,
        "models": models, "best_model": best, "gauge": {"low_to_medium": round(_cuts(presets)[0], 4), "medium_to_high": round(_cuts(presets)[1], 4)},
        "model_version": meta["version"], "trained_on": meta["dataset"],
    }
