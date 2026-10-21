"""Transaction risk: two separate signals, never presented as "fraud".

1. Supervised (logistic regression, trained offline on a public SYNTHETIC dataset; the trained file is models/txn_risk.joblib).
   Needs payer-side signals (new device, location mismatch, failed attempts ...). Explanations are exact:
   a linear model's contribution of each feature is coefficient x (value - training mean).
2. Anomaly (Isolation Forest, fitted on the merchant's own data). Uses only what a merchant sees: amount,
   time, how busy the outlet was, how often the payer paid recently, repeated references. It says
   "unusual", which is not the same as "fraudulent".

Both are turned into a percentile *within the dataset being viewed* (a relative ranking, not a probability).
Scoring is a triage aid for a human reviewer: weak signal, high false-positive rate. See docs/ML_REPORT_TXN_RISK.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .model import MerchantDataset, SIGNAL_CAT

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "txn_risk.joblib"
HIGH_PCT, MEDIUM_PCT = 99.0, 95.0  # top 1% = high, top 5% = medium
MIN_ROWS_ANOMALY = 50

SUP_NUM = ["log_amt", "amt_ratio", "hour", "is_weekend", "is_night", "sig_new_device", "sig_ip_mismatch", "sig_failed_attempts", "sig_loyalty", "sig_recurring"]
SUP_CAT = list(SIGNAL_CAT)
# Deliberately NOT used: the dataset's pre-computed 'velocity' / 'deviation' / 'frequency' scores (they may be derived from
# the label), its broken 'time_since_last_txn_min' (values like -351,322), and payment status (known only after the outcome).
REQUIRED_SIGNALS = ["sig_new_device", "sig_ip_mismatch", "sig_failed_attempts"]


def level_of(pct: float) -> str:
    return "high" if pct >= HIGH_PCT else "medium" if pct >= MEDIUM_PCT else "low"


# --------------------------------------------------------------------------- #
# supervised
# --------------------------------------------------------------------------- #
def sup_features(tx: pd.DataFrame) -> pd.DataFrame:
    """Single feature builder used by training AND inference (so they cannot drift apart)."""
    amt = tx["amount_paise"].to_numpy(dtype=float) / 100
    avg = pd.to_numeric(tx["sig_user_avg_value"], errors="coerce").clip(lower=1)
    hour = pd.to_datetime(tx["ts"]).dt.hour
    f = pd.DataFrame({
        "log_amt": np.log1p(amt), "amt_ratio": amt / avg, "hour": hour.to_numpy(),
        "is_weekend": (pd.to_datetime(tx["ts"]).dt.dayofweek >= 5).astype(int).to_numpy(), "is_night": (hour < 6).astype(int).to_numpy(),
    }, index=tx.index)
    for c in ("sig_new_device", "sig_ip_mismatch", "sig_failed_attempts", "sig_loyalty", "sig_recurring"):
        f[c] = pd.to_numeric(tx[c], errors="coerce")
    for c in SUP_CAT:
        f[c] = tx[c].astype("object").where(tx[c].notna(), "unknown").astype(str)
    return f[SUP_NUM + SUP_CAT]


def _pipeline(C: float) -> Pipeline:
    pre = ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), SUP_NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore"), SUP_CAT),
    ])
    return Pipeline([("pre", pre), ("lr", LogisticRegression(C=C, max_iter=3000))])


def train_supervised(tx: pd.DataFrame, y: np.ndarray, C: float = 0.5) -> dict[str, Any]:
    """Fit on `tx` (internal schema) and return the artifact. Splitting is the caller's job: use time order, never shuffling."""
    pipe = _pipeline(C).fit(sup_features(tx), y)
    x = pipe.named_steps["pre"].transform(sup_features(tx))
    x = x.toarray() if hasattr(x, "toarray") else np.asarray(x)
    return {"pipeline": pipe, "feature_means": x.mean(axis=0), "C": C}


def load_model(path: Path = MODEL_PATH) -> dict[str, Any] | None:
    try:
        return joblib.load(path) if path.exists() else None
    except Exception:  # noqa: BLE001 - a broken artifact must not take the dashboard down
        return None


_HUMAN = {
    "sig_new_device": lambda v, _: "the payment came from a device this payer has not used before" if v >= 0.5 else None,
    "sig_ip_mismatch": lambda v, _: "the payer's location did not match their usual location" if v >= 0.5 else None,
    "sig_failed_attempts": lambda v, _: f"{int(v)} failed attempt(s) by this payer in the last 24 hours" if v >= 1 else None,
    "amt_ratio": lambda v, _: f"the amount is {v:.1f}x this payer's usual payment" if v >= 1.5 else None,
    "log_amt": lambda v, _: f"a larger amount (about ₹{np.expm1(v):,.0f}) than most payments" if np.expm1(v) >= 2000 else None,
    "is_night": lambda v, _: "paid late at night (before 6 AM)" if v >= 0.5 else None,
    "hour": lambda v, _: None,
    "is_weekend": lambda v, _: "paid at a weekend" if v >= 0.5 else None,
    "sig_loyalty": lambda v, _: "the payer has a short or low history with the payment app" if v <= 0.3 else None,
    "sig_recurring": lambda v, _: None,
}
_CAT_LABEL = {"txn_type": "payment type", "payment_app": "payment app", "device_type": "device type", "kyc": "KYC status", "city_tier": "city tier"}


def score_supervised(model: dict[str, Any], tx: pd.DataFrame) -> tuple[np.ndarray, list[list[str]]]:
    """Probability (of being labelled fraud in the training data) and top reasons per row."""
    f = sup_features(tx)
    pipe: Pipeline = model["pipeline"]
    prob = pipe.predict_proba(f)[:, 1]
    x = pipe.named_steps["pre"].transform(f)
    x = x.toarray() if hasattr(x, "toarray") else np.asarray(x)
    contrib = (x - model["feature_means"]) * pipe.named_steps["lr"].coef_[0]
    names = pipe.named_steps["pre"].get_feature_names_out()
    # fold one-hot columns back to their source feature
    src = [n.split("__", 1)[1] for n in names]
    group = [next((c for c in SUP_CAT if s.startswith(c + "_")), s) for s in src]
    cat_val = {i: s[len(g) + 1:] for i, (s, g) in enumerate(zip(src, group)) if g in SUP_CAT}
    reasons: list[list[str]] = []
    cols = pd.Series(group)
    for r in range(len(f)):
        agg = pd.Series(contrib[r]).groupby(cols.to_numpy()).sum().sort_values(ascending=False)
        out: list[str] = []
        for feat, c in agg.items():
            if c <= 0.05 or len(out) >= 3:
                continue
            if feat in SUP_CAT:
                out.append(f"{_CAT_LABEL[feat]} '{f.iloc[r][feat]}' has been linked with more flagged payments in past data")
            elif (txt := _HUMAN[feat](float(f.iloc[r][feat]), None)):
                out.append(txt)
        reasons.append(out or ["a combination of small factors (no single strong reason)"])
    del cat_val
    return prob, reasons


# --------------------------------------------------------------------------- #
# anomaly (unsupervised, merchant-visible features only)
# --------------------------------------------------------------------------- #
def _prior_count(ts: pd.Series, window: pd.Timedelta) -> np.ndarray:
    """For each timestamp: how many OTHER timestamps in the same group fall in the window before it."""
    a = ts.to_numpy("datetime64[ns]").astype("int64")
    order = np.argsort(a, kind="stable")
    s = a[order]
    w = int(window.value)
    cnt = np.searchsorted(s, s, side="left") - np.searchsorted(s, s - w, side="left")
    out = np.empty(len(a), dtype=int)
    out[order] = cnt
    return out


def anomaly_features(tx: pd.DataFrame) -> pd.DataFrame:
    amt = tx["amount_paise"].to_numpy(dtype=float) / 100
    f = pd.DataFrame(index=tx.index)
    f["log_amt"] = np.log1p(amt)
    med = f.groupby(tx["outlet"])["log_amt"].transform("median")
    mad = (f["log_amt"] - med).abs().groupby(tx["outlet"]).transform("median").clip(lower=0.15)
    f["amt_z"] = (f["log_amt"] - med) / (1.4826 * mad)
    f["outlet_median_amt"] = np.expm1(med)
    h = tx["ts"].dt.hour + tx["ts"].dt.minute / 60
    f["hour_sin"], f["hour_cos"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
    f["hour"] = tx["ts"].dt.hour
    vel = np.zeros(len(tx), dtype=int)
    for _, idx in tx.groupby("outlet").indices.items():
        vel[idx] = _prior_count(tx["ts"].iloc[idx], pd.Timedelta(minutes=10))
    f["velocity_10m"] = vel
    rep = np.zeros(len(tx), dtype=int)
    has = tx["payer_ref"].notna().to_numpy()
    for _, idx in tx[has].groupby("payer_ref").indices.items():
        sub = np.flatnonzero(has)[idx]
        rep[sub] = _prior_count(tx["ts"].iloc[sub], pd.Timedelta(hours=24))
    f["payer_repeat_24h"] = rep
    f["dup_ref"] = (tx["is_dup_row"] | tx["txn_ref"].duplicated(keep=False)).astype(int)
    f["round_amount"] = ((tx["amount_paise"] % 10000 == 0) & (tx["amount_paise"] >= 10000)).astype(int)
    # how rare is this hour for this outlet?
    share = tx.groupby(["outlet", f["hour"]])["txn_ref"].transform("size") / tx.groupby("outlet")["txn_ref"].transform("size")
    f["hour_share"] = share
    return f


_AN_COLS = ["log_amt", "amt_z", "hour_sin", "hour_cos", "velocity_10m", "payer_repeat_24h", "dup_ref", "round_amount"]


_GROUPS = {"amount": ["log_amt", "amt_z"], "time": ["hour_sin", "hour_cos"], "velocity_10m": ["velocity_10m"], "payer_repeat_24h": ["payer_repeat_24h"], "dup_ref": ["dup_ref"], "round_amount": ["round_amount"]}


def _reason(group: str, row: pd.Series) -> str:
    if group == "amount":
        amt = np.expm1(row["log_amt"])
        return f"the amount (about ₹{amt:,.0f}) is {'higher' if row['amt_z'] > 0 else 'lower'} than is typical for this outlet (about ₹{row['outlet_median_amt']:,.0f})"
    if group == "time":
        return f"it was paid around {int(row['hour']):02d}:00, a time of day that is uncommon in this data"
    if group == "velocity_10m":
        return f"{int(row['velocity_10m'])} other payment(s) at this outlet in the 10 minutes before"
    if group == "payer_repeat_24h":
        return f"this payer had {int(row['payer_repeat_24h'])} other payment(s) in the previous 24 hours (a retry or repeat purchase is ordinary)"
    if group == "dup_ref":
        return "this transaction reference appears more than once"
    return "a round-number amount"


def score_anomaly(tx: pd.DataFrame) -> tuple[np.ndarray, list[list[str]]]:
    """Anomaly score per row, plus reasons for the top decile.

    Reasons are an attribution, not a guess: for each group of features, set it to the data's typical value and see how
    much the row's anomaly score drops. The groups with the biggest drops are what made the row look unusual.
    """
    f = anomaly_features(tx)
    scaler = StandardScaler().fit(f[_AN_COLS])
    x = scaler.transform(f[_AN_COLS])
    iso = IsolationForest(n_estimators=200, random_state=0, n_jobs=1).fit(x)
    raw = -iso.score_samples(x)  # higher = more unusual
    reasons: list[list[str]] = [[] for _ in range(len(f))]
    cand = np.flatnonzero(raw >= np.quantile(raw, 0.90))
    if len(cand):
        med = np.median(x, axis=0)
        drops = {}
        for g, cols in _GROUPS.items():
            xm = x[cand].copy()
            for c in cols:
                xm[:, _AN_COLS.index(c)] = med[_AN_COLS.index(c)]
            drops[g] = raw[cand] + iso.score_samples(xm)  # old score minus new score
        for k, i in enumerate(cand):
            ranked = sorted(((drops[g][k], g) for g in _GROUPS), reverse=True)
            picked = [g for d, g in ranked if d > 0.005][:2]
            row = f.iloc[i]
            reasons[i] = [_reason(g, row) for g in picked] or ["its combination of amount, time and activity differs from the rest of this data"]
    return raw, reasons


# --------------------------------------------------------------------------- #
# assessment for a dataset
# --------------------------------------------------------------------------- #
def assess_scored(ds: MerchantDataset) -> None:
    """Risk table from scores the fraud model already put on each payment (sample data): zone, probability and plain reasons."""
    tx = ds.transactions
    level = tx["zone"].map({"safe": "low", "check": "medium", "fraud": "high"}).fillna("low")
    prob = tx["fraud_prob"].astype(float)
    reasons = [[r for r in str(x).split("|") if r] or ["a combination of small factors"] for x in tx["reasons"].fillna("")]
    res = pd.DataFrame({"tid": tx["tid"].to_numpy(), "sup_prob": prob.to_numpy(), "sup_pct": (prob.rank(pct=True) * 100).to_numpy(), "sup_reasons": reasons,
                        "an_pct": np.nan, "an_reasons": [[] for _ in range(len(tx))], "sup_level": level.to_numpy(), "an_level": None, "level": level.to_numpy(),
                        "score": (prob * 100).to_numpy()})
    res["alert"] = res["level"].isin(["medium", "high"])
    res["signal"] = np.where(res["alert"], "risk_model", "none")
    ds.risk = res.set_index("tid")
    ds.risk_info = {"supervised": {"available": True, "model": "XGBoost (the model on the Fraud check page)", "trained_on": "synthetic IEEE-layout payments, days 0-119",
                                   "split": "These payments are from days 150-182, which the model never saw."}, "anomaly": {"available": False, "reason": "Not used for this data."},
                    "thresholds": {}}


def assess(ds: MerchantDataset, model: dict[str, Any] | None = None) -> None:
    """Fill ds.risk (one row per transaction) and ds.risk_info."""
    tx = ds.transactions.reset_index(drop=True)
    n = len(tx)
    info: dict[str, Any] = {"supervised": {"available": False}, "anomaly": {"available": False}, "thresholds": {"high_percentile": HIGH_PCT, "medium_percentile": MEDIUM_PCT}}
    res = pd.DataFrame({"tid": tx["tid"], "sup_prob": np.nan, "sup_pct": np.nan, "sup_reasons": [[] for _ in range(n)], "an_pct": np.nan, "an_reasons": [[] for _ in range(n)]})

    have_signals = all(c in tx and tx[c].notna().mean() > 0.5 for c in REQUIRED_SIGNALS)
    if model is None:
        info["supervised"]["reason"] = "The risk model file (models/txn_risk.joblib) is missing."
    elif not have_signals:
        info["supervised"]["reason"] = "This data has no payer-side signals (new device, location mismatch, failed attempts), which the risk model needs."
    elif n:
        prob, why = score_supervised(model, tx)
        res["sup_prob"], res["sup_reasons"] = prob, why
        res["sup_pct"] = pd.Series(prob).rank(pct=True, method="average").to_numpy() * 100
        info["supervised"] = {"available": True, **{k: model["meta"][k] for k in ("model", "trained_on", "split", "metrics", "caveat") if k in model.get("meta", {})}}
    if n >= MIN_ROWS_ANOMALY:
        raw, why = score_anomaly(tx)
        res["an_pct"] = pd.Series(raw).rank(pct=True, method="average").to_numpy() * 100
        res["an_reasons"] = why
        info["anomaly"] = {"available": True, "method": "Isolation Forest on amount, time of day, outlet activity, payer repeat rate and repeated references", "rows": n}
    else:
        info["anomaly"]["reason"] = f"At least {MIN_ROWS_ANOMALY} transactions are needed to learn what is normal for this business."

    res["sup_level"] = res["sup_pct"].map(lambda p: None if pd.isna(p) else level_of(p))
    res["an_level"] = res["an_pct"].map(lambda p: None if pd.isna(p) else level_of(p))
    order = {None: 0, "low": 1, "medium": 2, "high": 3}
    inv = {v: k for k, v in order.items() if k}
    res["level"] = [inv.get(max(order[a], order[b]), None) for a, b in zip(res["sup_level"], res["an_level"])]
    res["score"] = res[["sup_pct", "an_pct"]].max(axis=1)
    res["alert"] = res["level"].isin(["medium", "high"])
    res["signal"] = np.where(res["sup_level"].isin(["medium", "high"]), np.where(res["an_level"].isin(["medium", "high"]), "both", "risk_model"), np.where(res["an_level"].isin(["medium", "high"]), "unusual_activity", "none"))
    ds.risk, ds.risk_info = res.set_index("tid"), info
