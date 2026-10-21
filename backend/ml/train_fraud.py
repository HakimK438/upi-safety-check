"""Train, compare and honestly evaluate the payment-fraud models.     Run from backend/:  python ml/train_fraud.py [--data synth|real] [--skip-ulb]

--data synth (default): SYNTHETIC data in the IEEE-CIS layout (ml/make_synthetic_ieee.py). Every number is synthetic and
  labelled so; 4 models (logistic regression, random forest, XGBoost, PyTorch neural network); one cut-off chosen on
  validation by best F1 (target: 90%+ precision AND recall). The earlier real-data results are attached as "real_check".
--data real: the original real IEEE-CIS run described below.

Data (both REAL, see CLAUDE.md "Data decision"):
  IEEE-CIS (Vesta)  data/raw/ieee_cis      590k real e-commerce payments, real chargeback labels -> the shipped model
  ULB (Worldline)   data/raw/ulb_creditcard 285k real card payments                               -> second benchmark

Method (same for every model):
  * time order only: train (days 0-119) -> validation (120-149: pick model, calibrate, pick threshold) -> test (150-182: report).
  * training rows: every fraud + a random 1-in-4 of genuine payments (speed); validation/test keep the real fraud rate.
  * walk-forward: train on everything before a 30-day period, test on that period -> stability + drift.
  * 5 algorithms (logistic regression, random forest, XGBoost, LightGBM, MLP neural network) + a rule-count baseline.
  * isotonic calibration on validation -> probabilities; Brier score + calibration curve.
  * 95% bootstrap confidence intervals; threshold chosen on validation by money: missed fraud costs its amount,
    a false alarm costs REVIEW_COST.
Writes models/fraud_models.joblib, models/registry.json, docs/ml/fraud_results.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score, roc_curve
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, QuantileTransformer, StandardScaler
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")
BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
from app.merchant import fraud_features as ff  # noqa: E402
from app.merchant.nn_model import TorchMLP  # noqa: E402

RAW = BACKEND / "data" / "raw"
CACHE = RAW / "ieee_cis" / "_features.pkl"
WF_CACHE = RAW / "ieee_cis" / "_walk_forward.json"
SYNTH = BACKEND / "data"  # the synthetic data
OUT_JSON = ROOT / "docs" / "ml" / "fraud_results.json"
REAL_JSON = ROOT / "docs" / "ml" / "fraud_results_real.json"  # frozen copy of the last real-data run
MODEL_PATH = BACKEND / "models" / "fraud_models.joblib"
REGISTRY = BACKEND / "models" / "registry.json"
REVIEW_COST = 25.0  # dataset currency (USD): staff time + a delayed genuine customer when a good payment is held
NEG_KEEP = 0.25
SEED = 0
MODELS = ["logreg", "rf", "xgb", "lgbm", "mlp"]
SYNTH_MODELS = ["logreg", "rf", "xgb", "mlp"]
NAMES = {"logreg": "Logistic regression", "rf": "Random forest", "xgb": "XGBoost", "lgbm": "LightGBM", "mlp": "Neural network (PyTorch)", "rule": "Rule baseline (count of warning signs)"}
KIND = {"logreg": "Linear model, the classic baseline", "rf": "Many independent decision trees, majority vote", "xgb": "Gradient-boosted trees",
        "lgbm": "Gradient-boosted trees, fast and strong on tables", "mlp": "Neural network: 3 layers (256-128-64), batch norm, dropout, early stopping", "rule": "Counts the 8 warning signs; no learning"}


# ------------------------------------------------------------------ models
def make(mid: str, num: list[str], cat: list[str], pos_weight: float) -> Pipeline:
    # the network gets rank-normalised inputs (heavy-tailed counts and amounts otherwise swamp it)
    scale = QuantileTransformer(output_distribution="normal", n_quantiles=200, random_state=SEED) if mid == "mlp" else StandardScaler()
    tr = [("num", Pipeline([("imp", SimpleImputer(strategy="median", add_indicator=True)), ("sc", scale)]), num)]
    if cat:
        tr.append(("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=50, sparse_output=False), cat))
    pre = ColumnTransformer(tr, verbose_feature_names_out=True)
    m: Any
    if mid == "logreg":
        m = LogisticRegression(C=0.3, class_weight="balanced", max_iter=3000)
    elif mid == "rf":
        m = RandomForestClassifier(n_estimators=200, min_samples_leaf=10, max_depth=18, max_features="sqrt", class_weight="balanced_subsample",
                                   max_samples=0.5, n_jobs=-1, random_state=SEED)
    elif mid == "xgb":
        m = XGBClassifier(n_estimators=500, max_depth=6, learning_rate=0.05, subsample=0.8, colsample_bytree=0.7, min_child_weight=5,
                          scale_pos_weight=pos_weight, tree_method="hist", n_jobs=-1, random_state=SEED, verbosity=0)
    elif mid == "lgbm":
        m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.04, num_leaves=63, min_child_samples=50, subsample=0.8, subsample_freq=1,
                               colsample_bytree=0.7, reg_lambda=1.0, scale_pos_weight=pos_weight, n_jobs=-1, random_state=SEED, verbose=-1)
    elif mid == "mlp":
        m = TorchMLP(pos_weight=max(1.0, pos_weight / 2), random_state=SEED)
    else:
        raise ValueError(mid)
    return Pipeline([("pre", pre), ("m", m)])


def downsample(mask: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Training rows: every fraud + NEG_KEEP of genuine rows (fixed seed)."""
    keep = np.random.default_rng(SEED).random(len(y)) < NEG_KEEP
    return mask & ((y == 1) | keep)


def fit_score(mid: str, X: pd.DataFrame, y: np.ndarray, trm: np.ndarray, others: list[np.ndarray], num: list[str], cat: list[str]):
    idx = downsample(trm, y)
    pw = float((y[idx] == 0).sum() / max(1, (y[idx] == 1).sum()))
    p = make(mid, num, cat, pw if mid in ("xgb", "lgbm", "mlp") else 1.0).fit(X.loc[idx, num + cat], y[idx])
    return p, [p.predict_proba(X.loc[o, num + cat])[:, 1] for o in others]


# ------------------------------------------------------------------ metrics
def at_threshold(y: np.ndarray, p: np.ndarray, thr: float, amt: np.ndarray | None = None) -> dict[str, float]:
    flag = p >= thr
    tp, fp = int((flag & (y == 1)).sum()), int((flag & (y == 0)).sum())
    fn, tn = int((~flag & (y == 1)).sum()), int((~flag & (y == 0)).sum())
    pr, rc = tp / max(1, tp + fp), tp / max(1, tp + fn)
    r = {"threshold": float(thr), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": pr, "recall": rc, "f1": 2 * pr * rc / max(1e-9, pr + rc),
         "accuracy": (tp + tn) / len(y), "fpr": fp / max(1, fp + tn), "flags_per_1000": 1000 * flag.mean(), "false_alarms_per_1000": 1000 * fp / len(y)}
    if amt is not None:
        r["fraud_value_caught"] = float(amt[flag & (y == 1)].sum())
        r["fraud_value_missed"] = float(amt[~flag & (y == 1)].sum())
        r["cost"] = r["fraud_value_missed"] + REVIEW_COST * fp
    return r


def cost_threshold(y: np.ndarray, p: np.ndarray, amt: np.ndarray) -> float:
    cands = np.unique(np.quantile(p, np.linspace(0.5, 0.999, 300)))
    costs = [amt[(p < t) & (y == 1)].sum() + REVIEW_COST * ((p >= t) & (y == 0)).sum() for t in cands]
    return float(cands[int(np.argmin(costs))])


def f1_threshold(y: np.ndarray, p: np.ndarray) -> float:
    """The single cut-off with the best F1 (precision and recall together) on validation."""
    prec, rec, th = precision_recall_curve(y, p)
    f1 = 2 * prec[:-1] * rec[:-1] / np.maximum(1e-9, prec[:-1] + rec[:-1])
    return float(th[int(np.argmax(f1))])


def thr_for_recall(y: np.ndarray, p: np.ndarray, target: float) -> float:
    pos = np.sort(p[y == 1])[::-1]
    return float(pos[min(len(pos) - 1, max(0, int(np.ceil(target * len(pos))) - 1))])


def thr_for_precision(y: np.ndarray, p: np.ndarray, target: float) -> float:
    prec, _, th = precision_recall_curve(y, p)
    ok = np.flatnonzero(prec[:-1] >= target)
    return float(th[ok[0]]) if len(ok) else float(th[-1])


def triage(yv: np.ndarray, pv: np.ndarray, yt: np.ndarray, pt: np.ndarray, amt: np.ndarray, target: float = 0.9,
           cuts: tuple[float, float] | None = None) -> dict[str, Any]:
    """Three zones, both cut-offs chosen on VALIDATION: Block (precision >= target), Check, Approve (Block+Check recall >= target).
    `cuts` = (check, block) overrides them, for data where one cut-off already meets both targets."""
    block = thr_for_precision(yv, pv, target)
    check = thr_for_recall(yv, pv, target)
    if cuts is not None:
        check, block = cuts
    zb, zc = pt >= block, (pt >= check) & (pt < block)
    za = ~(zb | zc)
    n, f = len(yt), max(1, yt.sum())
    zone = lambda m: {"payments": int(m.sum()), "share": float(m.mean()), "fraud": int(yt[m].sum()), "fraud_rate": float(yt[m].mean()) if m.any() else 0.0,  # noqa: E731
                      "share_of_all_fraud": float(yt[m].sum() / f), "fraud_value": float(amt[m & (yt == 1)].sum())}
    return {"target": target, "block_threshold": block, "check_threshold": check, "block": zone(zb), "check": zone(zc), "approve": zone(za),
            "block_precision": float(yt[zb].mean()) if zb.any() else 0.0, "block_recall": float(yt[zb].sum() / f),
            "flag_recall": float(yt[zb | zc].sum() / f), "approve_clean_rate": float(1 - yt[za].mean()) if za.any() else 1.0, "test_payments": n}


def bootstrap_ci(y: np.ndarray, p: np.ndarray, thr: float, n: int = 200) -> dict[str, list[float]]:
    rng = np.random.default_rng(SEED)
    acc: dict[str, list[float]] = {"roc_auc": [], "pr_auc": [], "precision": [], "recall": [], "f1": []}
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        acc["roc_auc"].append(roc_auc_score(y[i], p[i]))
        acc["pr_auc"].append(average_precision_score(y[i], p[i]))
        r = at_threshold(y[i], p[i], thr)
        for k in ("precision", "recall", "f1"):
            acc[k].append(r[k])
    return {k: [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)] for k, v in acc.items()}


def curves(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    fpr, tpr, _ = roc_curve(y, p)
    grid = np.concatenate([np.linspace(0, 0.1, 41), np.linspace(0.1, 1, 61)[1:]])  # dense where merchants operate (low FPR)
    prec, rec, _ = precision_recall_curve(y, p)
    order = np.argsort(rec, kind="stable")
    prec_i = np.maximum.accumulate(prec)  # recall falls along the array: best precision at recall >= r
    rg = np.linspace(0, 1, 101)
    return {"roc": [[round(float(a), 4), round(float(b), 4)] for a, b in zip(grid, np.interp(grid, fpr, tpr))],
            "pr": [[round(float(a), 4), round(float(b), 4)] for a, b in zip(rg, np.interp(rg, rec[order], prec_i[order]))]}


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict[str, float]]:
    qs = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    idx = np.clip(np.searchsorted(qs, p, side="right") - 1, 0, len(qs) - 2)
    return [{"predicted": round(float(p[idx == b].mean()), 4), "actual": round(float(y[idx == b].mean()), 4), "n": int((idx == b).sum())}
            for b in range(len(qs) - 1) if (idx == b).any()]


def sweep(y: np.ndarray, p: np.ndarray, amt: np.ndarray) -> list[dict[str, float]]:
    ths = np.unique(np.quantile(p, np.concatenate([np.linspace(0.5, 0.99, 70), np.linspace(0.99, 0.9998, 30)])))
    keep = ("threshold", "precision", "recall", "f1", "flags_per_1000", "false_alarms_per_1000", "cost", "fraud_value_caught", "fraud_value_missed")
    return [{k: round(float(v), 5) for k, v in at_threshold(y, p, t, amt).items() if k in keep} for t in ths]


def summ(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {"roc_auc": round(float(roc_auc_score(y, p)), 4), "pr_auc": round(float(average_precision_score(y, p)), 4), "brier": round(float(brier_score_loss(y, p)), 5)}


# ------------------------------------------------------------------ one experiment
def experiment(tag: str, X: pd.DataFrame, y: np.ndarray, period: np.ndarray, amt: np.ndarray, num: list[str], cat: list[str],
               val_p: int, test_p: int, wf: list[int], rule: np.ndarray | None, models: list[str], thr_mode: str = "cost",
               preset_targets: tuple[float, float] = (0.8, 0.7)) -> dict[str, Any]:
    print(f"\n=== {tag}: {len(X)} rows, {len(num) + len(cat)} inputs, fraud rate {y.mean():.4f}", flush=True)
    tr, va, te = period < val_p, period == val_p, period == test_p
    res: dict[str, Any] = {"tag": tag, "rows": int(len(X)), "n_features": len(num) + len(cat), "base_rate": float(y.mean()),
                           "train_rows": int(downsample(tr, y).sum()), "train_rows_before_sampling": int(tr.sum()), "val_rows": int(va.sum()),
                           "test_rows": int(te.sum()), "test_fraud": int(y[te].sum()), "base_rate_test": float(y[te].mean()), "models": {}, "walk_forward": {}}
    wf_cache = json.loads(WF_CACHE.read_text()) if WF_CACHE.exists() else {}
    for mid in models if wf else []:
        key = f"{tag}|{mid}|{len(X)}|{len(num)}"
        folds = wf_cache.get(key)
        if folds is None:  # walk-forward is the slow part; cache it so a re-run only retrains the final models
            folds = []
            for pp in wf:
                _, (s,) = fit_score(mid, X, y, period < pp, [period == pp], num, cat)
                m = period == pp
                folds.append({"period": int(pp), "n": int(m.sum()), "fraud": int(y[m].sum()), "roc_auc": round(float(roc_auc_score(y[m], s)), 4),
                              "pr_auc": round(float(average_precision_score(y[m], s)), 4), "base_rate": round(float(y[m].mean()), 4)})
            wf_cache[key] = folds
            WF_CACHE.write_text(json.dumps(wf_cache))
        pr = np.array([f["pr_auc"] for f in folds])
        ra = np.array([f["roc_auc"] for f in folds])
        res["walk_forward"][mid] = {"folds": folds, "pr_auc_mean": float(pr.mean()), "pr_auc_std": float(pr.std()), "roc_auc_mean": float(ra.mean()), "roc_auc_std": float(ra.std())}
        print(f"  walk-forward {mid:6s} PR-AUC {pr.mean():.3f} ± {pr.std():.3f} | ROC-AUC {ra.mean():.3f}", flush=True)

    fitted: dict[str, Any] = {}
    for mid in models:
        t0 = time.time()
        pipe, (sv, st) = fit_score(mid, X, y, tr, [va, te], num, cat)
        fit_s = time.time() - t0
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(sv, y[va])
        cv, ct = iso.predict(sv), np.clip(iso.predict(st) + st * 1e-9, 0, 1)  # tiny raw-score term keeps the ranking inside isotonic steps
        thr = f1_threshold(y[va], cv) if thr_mode == "f1" else cost_threshold(y[va], cv, amt[va])
        t1 = time.time()
        pipe.predict_proba(X.loc[te, num + cat].iloc[:1000])
        r = {"name": NAMES[mid], "kind": KIND[mid], "val": summ(y[va], sv), "test": summ(y[te], st), "test_brier_calibrated": round(float(brier_score_loss(y[te], ct)), 5),
             "threshold": thr, "at_threshold": at_threshold(y[te], ct, thr, amt[te]), "ci95": bootstrap_ci(y[te], ct, thr), "curves": curves(y[te], st),
             "train_seconds": round(fit_s, 1), "ms_per_1000_predictions": round((time.time() - t1) * 1000, 1)}
        fitted[mid] = {"pipeline": pipe, "calibrator": iso, "threshold": thr, "_sv": sv, "_ct": ct}
        res["models"][mid] = r
        a = r["at_threshold"]
        print(f"  {mid:6s} val PR {r['val']['pr_auc']:.3f} | test ROC {r['test']['roc_auc']:.3f} PR {r['test']['pr_auc']:.3f} | P {a['precision']:.2f} R {a['recall']:.2f} F1 {a['f1']:.2f} ({fit_s:.0f}s)", flush=True)

    if rule is not None:
        rv, rt = np.clip(rule[va] / 8 + 1e-6 * np.random.default_rng(1).random(va.sum()), 0, 1), np.clip(rule[te] / 8 + 1e-6 * np.random.default_rng(2).random(te.sum()), 0, 1)  # score 0-8 -> 0-1
        thr_r = cost_threshold(y[va], rv, amt[va])
        res["models"]["rule"] = {"name": NAMES["rule"], "kind": KIND["rule"], "val": summ(y[va], rv), "test": summ(y[te], rt), "threshold": thr_r,
                                 "at_threshold": at_threshold(y[te], rt, thr_r, amt[te]), "ci95": bootstrap_ci(y[te], rt, thr_r), "curves": curves(y[te], rt)}
    best = max(models, key=lambda m: res["models"][m]["val"]["pr_auc"])  # chosen on VALIDATION
    res["best"] = best
    b = fitted[best]
    cv, ct = b["calibrator"].predict(b["_sv"]), b["_ct"]
    presets = {"fewer_false_alarms": thr_for_precision(y[va], cv, preset_targets[0]), "balanced": b["threshold"], "catch_more": thr_for_recall(y[va], cv, preset_targets[1])}
    res["presets"] = {k: at_threshold(y[te], ct, v, amt[te]) for k, v in presets.items()}
    # synthetic (best-F1) runs: Block = the single best-F1 cut-off, Check = down to the 95%-recall cut-off
    res["triage"] = triage(y[va], cv, y[te], ct, amt[te], cuts=(presets["catch_more"], presets["balanced"]) if thr_mode == "f1" else None)
    res["calibration"] = {"before": calibration(y[te], res_raw(fitted[best], X, te, num, cat)), "after": calibration(y[te], ct)}
    res["sweep"] = sweep(y[te], ct, amt[te])
    res["_fitted"], res["_split"] = fitted, (tr, va, te)
    return res


def res_raw(f: dict[str, Any], X: pd.DataFrame, te: np.ndarray, num: list[str], cat: list[str]) -> np.ndarray:
    return f["pipeline"].predict_proba(X.loc[te, num + cat])[:, 1]


# ------------------------------------------------------------------ explanations / extras
def contributions(pipe: Pipeline, X: pd.DataFrame, num: list[str], cat: list[str]) -> pd.DataFrame:
    """Per-feature SHAP values (log-odds) from LightGBM / XGBoost, folded back onto the original inputs."""
    Z = pipe["pre"].transform(X[num + cat])
    names = list(pipe["pre"].get_feature_names_out())
    m = pipe["m"]
    if isinstance(m, lgb.LGBMClassifier):
        c = m.booster_.predict(Z, pred_contrib=True)[:, :-1]
    else:
        import xgboost as xgb
        c = m.get_booster().predict(xgb.DMatrix(Z), pred_contribs=True)[:, :-1]
    out = pd.DataFrame(0.0, index=X.index, columns=num + cat)
    for j, nm in enumerate(names):
        base = nm.split("__", 1)[-1].removeprefix("missingindicator_")
        col = base if base in out.columns else next((k for k in cat if base.startswith(k + "_")), None)
        if col:
            out[col] += c[:, j]
    return out


def select_v(n_keep: int = 30) -> list[str]:
    """Pick ~30 of the 339 masked V columns: drop near-duplicates (|r| > 0.95), then keep the most useful by LightGBM gain."""
    hdr = pd.read_csv(RAW / "ieee_cis" / "train_transaction.csv", nrows=0).columns
    vcols = [c for c in hdr if c.startswith("V")]
    s = pd.read_csv(RAW / "ieee_cis" / "train_transaction.csv", usecols=["isFraud", "TransactionDT", *vcols], dtype={c: "float32" for c in vcols})
    s = s[s["TransactionDT"] < 120 * ff.DAY]
    s = s[(s["isFraud"] == 1) | (np.random.default_rng(SEED).random(len(s)) < 0.15)]
    corr = s[vcols].corr().abs().to_numpy()
    nun = s[vcols].nunique().to_numpy()
    kept: list[int] = []
    for i in np.argsort(-nun):
        if all(corr[i, j] < 0.95 or np.isnan(corr[i, j]) for j in kept):
            kept.append(i)
    cand = [vcols[i] for i in kept]
    m = lgb.LGBMClassifier(n_estimators=200, num_leaves=31, learning_rate=0.05, verbose=-1, random_state=SEED).fit(s[cand], s["isFraud"])
    gain = pd.Series(m.booster_.feature_importance("gain"), index=cand).sort_values(ascending=False)
    print(f"V columns: {len(vcols)} -> {len(cand)} after removing duplicates -> top {n_keep} by gain", flush=True)
    return list(gain.index[:n_keep])


def data_insights(df: pd.DataFrame, F: pd.DataFrame, y: np.ndarray) -> dict[str, Any]:
    base = float(y.mean())

    def by(col: pd.Series, min_n: int = 500) -> list[dict[str, Any]]:
        g = pd.DataFrame({"k": col.astype(str), "y": y}).groupby("k")["y"].agg(["mean", "size"])
        g = g[g["size"] >= min_n].sort_values("mean", ascending=False)
        return [{"group": k, "n": int(r["size"]), "fraud_rate": round(float(r["mean"]), 4)} for k, r in g.iterrows()]

    amt = df["TransactionAmt"].to_numpy(float)
    edges = [0, 25, 50, 100, 200, 500, 1000, 1e9]
    lab = ["<25", "25-50", "50-100", "100-200", "200-500", "500-1k", "1k+"]
    ab = pd.cut(amt, edges, labels=lab, right=False)
    amount = [{"band": b, "share_fraud": round(float(((ab == b) & (y == 1)).sum() / max(1, y.sum())), 4), "share_genuine": round(float(((ab == b) & (y == 0)).sum() / max(1, (y == 0).sum())), 4),
               "fraud_rate": round(float(y[ab == b].mean()), 4)} for b in lab]
    hours = [{"hour": int(h), "fraud_rate": round(float(y[F["hour"] == h].mean()), 4), "n": int((F["hour"] == h).sum())} for h in range(24)]
    daily = pd.DataFrame({"d": (df["TransactionDT"] // ff.DAY // 7).astype(int), "y": y}).groupby("d")["y"].agg(["mean", "size"])
    flags = [{"flag": k, "label": ff.LABELS[k], "n": int((F[k] == 1).sum()), "fraud_rate": round(float(y[F[k] == 1].mean()), 4) if (F[k] == 1).any() else 0.0,
              "lift": round(float(y[F[k] == 1].mean() / base), 2) if (F[k] == 1).any() else 0.0} for k in ff.FLAGS]
    rs = [{"warning_signs": int(k), "n": int((F["rule_score"] == k).sum()), "fraud_rate": round(float(y[F["rule_score"] == k].mean()), 4)} for k in range(0, 6) if (F["rule_score"] == k).sum() > 50]
    return {"rows": int(len(y)), "fraud": int(y.sum()), "base_rate": round(base, 4), "days": int(df["TransactionDT"].max() // ff.DAY) + 1,
            "fraud_amount_median": round(float(np.median(amt[y == 1])), 2), "genuine_amount_median": round(float(np.median(amt[y == 0])), 2),
            "by_product": by(df["ProductCD"]), "by_device": by(F["DeviceType"]), "by_email": by(F["email"], 2000)[:10], "by_card": by(df["card6"].fillna("unknown")),
            "by_os": by(F["os"]), "amount": amount, "hours": hours, "weekly": [{"week": int(k), "fraud_rate": round(float(r["mean"]), 4), "n": int(r["size"])} for k, r in daily.iterrows()],
            "flags": flags, "rule_score": rs}


def example_inputs(F: pd.DataFrame, i: int, amt: float) -> dict[str, Any]:
    r = F.loc[i]

    def num(k: str) -> float | None:
        v = r[k]
        return None if pd.isna(v) else round(float(v), 2)

    prior = int(r["uid_prior_n"])
    return {"amount": round(amt, 2), "hour": int(r["hour"]), "product": r["ProductCD"], "network": r["card4"], "instrument": r["card6"],
            "email_domain": None if r["email"] == "missing" else (r["email"] if r["email"] != "other" else "other-domain.com"), "device_type": r["DeviceType"],
            "os": r["os"], "browser": r["browser"], "distance_km": num("dist1"), "account_age_days": num("account_age_days"),
            "customer_prior_payments": prior, "customer_usual_amount": round(amt / float(r["amt_vs_uid"]), 2) if prior and not pd.isna(r["amt_vs_uid"]) and r["amt_vs_uid"] else None,
            "hours_since_last_payment": num("uid_gap_h"), "payments_last_hour": int(r["uid_n_1h"]), "payments_last_24h": int(r["uid_n_24h"]),
            "new_device": bool(r["uid_new_device"]), "devices_seen": int(r["uid_devices_seen"]) or 1, "accounts_on_device_7d": int(r["device_uids_7d"]) if not pd.isna(r["device_uids_7d"]) else 1,
            "prior_fraud": int(r["uid_prior_fraud"])}


def learning_curve(X: pd.DataFrame, y: np.ndarray, tr: np.ndarray, te: np.ndarray, mid: str, num: list[str], cat: list[str]) -> list[dict[str, Any]]:
    idx = np.flatnonzero(tr)
    pts = []
    for frac in (0.1, 0.25, 0.5, 0.75, 1.0):
        m = np.zeros(len(y), bool)
        m[idx[int(len(idx) * (1 - frac)):]] = True  # most recent part of the training window (time order kept)
        _, (s,) = fit_score(mid, X, y, m, [te], num, cat)
        pts.append({"fraction": frac, "train_rows": int(downsample(m, y).sum()), "pr_auc": round(float(average_precision_score(y[te], s)), 4), "roc_auc": round(float(roc_auc_score(y[te], s)), 4)})
        print(f"  learning curve {frac:.2f}: PR-AUC {pts[-1]['pr_auc']:.3f}", flush=True)
    return pts


def strip(res: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in res.items() if not k.startswith("_")}


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


# ------------------------------------------------------------------ main
def run_ieee() -> dict[str, Any]:
    t0 = time.time()
    if CACHE.exists():
        df, F, vsel = pd.read_pickle(CACHE)
    else:
        vsel = select_v()
        df = ff.load_ieee(RAW / "ieee_cis", vsel)
        F = ff.build(df, with_research=True)
        pd.to_pickle((df[["TransactionID", "isFraud", "TransactionDT", "TransactionAmt", "ProductCD", "card6"]], F, vsel), CACHE)
    y = df["isFraud"].to_numpy(int)
    amt = df["TransactionAmt"].to_numpy(float)
    period = np.minimum(df["TransactionDT"].to_numpy() // (30 * ff.DAY), 5).astype(int)  # 0..5, ~30 days each
    print(f"features ready in {time.time() - t0:.0f}s: {F.shape}", flush=True)

    dnum, dcat = ff.DEPLOY_NUM, ff.DEPLOY_CAT
    rnum = dnum + ff.RESEARCH_EXTRA_NUM + vsel
    dep = experiment("Deployable model (merchant/gateway fields)", F, y, period, amt, dnum, dcat, 4, 5, [2, 3, 4, 5], F["rule_score"].to_numpy(float), MODELS)
    res = experiment("Research model (+ hidden bank-side columns)", F, y, period, amt, rnum, dcat, 4, 5, [], None, ["lgbm", "xgb"])

    # explanations from the best tree booster of the deployable set
    tree = max(("lgbm", "xgb"), key=lambda m: dep["models"][m]["val"]["pr_auc"])
    dep["explainer"] = tree
    tr, va, te = dep["_split"]
    te_idx = np.flatnonzero(te)
    samp = np.random.default_rng(SEED).choice(te_idx, 20000, replace=False)
    contrib = contributions(dep["_fitted"][tree]["pipeline"], F.loc[samp], dnum, dcat)
    imp = contrib.abs().mean().sort_values(ascending=False)
    dep["importance"] = [{"feature": k, "label": ff.LABELS.get(k, k), "mean_abs_shap": round(float(v), 4)} for k, v in imp.items()]
    dep["learning_curve"] = learning_curve(F, y, tr, te, dep["best"], dnum, dcat)

    # real examples from the TEST period (unseen by every model) for the page's "load a real case" buttons
    best = dep["_fitted"][dep["best"]]
    ct = best["_ct"]
    rng = np.random.default_rng(7)
    pick = lambda m, k: list(rng.choice(te_idx[m], min(k, int(m.sum())), replace=False))  # noqa: E731
    thr = best["threshold"]
    cases = {"caught_fraud": pick((y[te] == 1) & (ct >= thr) & (F.loc[te, "uid_prior_n"].to_numpy() > 0), 3), "missed_fraud": pick((y[te] == 1) & (ct < thr), 2),
             "genuine": pick((y[te] == 0) & (ct < thr * 0.3) & (F.loc[te, "uid_prior_n"].to_numpy() > 2), 3), "false_alarm": pick((y[te] == 0) & (ct >= thr), 2)}
    dep["examples"] = [{"kind": k, "transaction_id": int(df.loc[i, "TransactionID"]), "actual_fraud": int(y[i]), "inputs": example_inputs(F, i, float(amt[i]))}
                       for k, ids in cases.items() for i in ids]

    # save every deployable model (for side-by-side live scoring) + registry
    version = time.strftime("v%Y.%m.%d-%H%M")
    meta = {"version": version, "best": dep["best"], "best_name": NAMES[dep["best"]], "explainer": tree, "dataset": "IEEE-CIS (Vesta), real e-commerce card payments",
            "train_window": "days 0-119 (all fraud + 25% of genuine)", "calibration_window": "days 120-149", "test_window": "days 150-182",
            "train_rows": dep["train_rows"], "features": dnum + dcat, "git_commit": git_commit(), "test": dep["models"][dep["best"]]["test"],
            "presets": {k: v["threshold"] for k, v in dep["presets"].items()}, "review_cost": REVIEW_COST, "trained_at": time.strftime("%Y-%m-%d %H:%M")}
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"models": {m: {k: v for k, v in f.items() if not k.startswith("_")} for m, f in dep["_fitted"].items()}, "num": dnum, "cat": dcat, "meta": meta}, MODEL_PATH, compress=3)
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []
    reg.append({**meta, "artifact": str(MODEL_PATH.relative_to(BACKEND)).replace("\\", "/")})
    REGISTRY.write_text(json.dumps(reg, indent=2))
    dep["registry"] = meta
    insights = data_insights(df, F, y)
    return {"ieee": strip(dep), "ieee_research": strip(res), "insights": insights}


def run_ulb() -> dict[str, Any] | None:
    path = RAW / "ulb_creditcard" / "creditcard.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    y = df.pop("Class").to_numpy(int)
    amt = df["Amount"].to_numpy(float)
    X = df.drop(columns=["Time", "Amount"]).assign(log_amt=np.log1p(amt), hour=(df["Time"] // 3600) % 24).reset_index(drop=True)
    period = np.minimum(df["Time"].rank(pct=True, method="first").to_numpy() * 10, 9.999).astype(int)  # 10 equal time slices
    r = experiment("ULB real card payments (benchmark)", X, y, period, amt, list(X.columns), [], 6, 7, [7, 8, 9], (X["V14"] < -5).astype(float).to_numpy(), MODELS)
    return {"ulb": strip(r)}


# ------------------------------------------------------------------ synthetic data (default)
EDA_HIST = [("amount", "Payment amount ($)", [0, 10, 25, 50, 100, 200, 500, 1000, 1e9], ["<10", "10-25", "25-50", "50-100", "100-200", "200-500", "500-1k", "1k+"]),
            ("account_age_days", "Account age (days)", [0, 1, 7, 30, 90, 365, 1e9], ["<1", "1-7", "7-30", "30-90", "90-365", "365+"]),
            ("uid_n_1h", "Earlier payments by this customer in the last hour", [0, 1, 2, 3, 5, 1e9], ["0", "1", "2", "3-4", "5+"]),
            ("amt_vs_uid", "Amount vs the customer's usual", [0, 0.5, 1.5, 3, 6, 1e9], ["<0.5x", "0.5-1.5x", "1.5-3x", "3-6x", "6x+"]),
            ("device_uids_7d", "Accounts seen on this device in 7 days", [0, 1, 2, 3, 6, 1e9], ["0", "1", "2", "3-5", "6+"]),
            ("dist1", "Distance from the usual place (km)", [0, 10, 50, 100, 500, 1e9], ["<10", "10-50", "50-100", "100-500", "500+"])]
EDA_CORR = ["log_amt", "hour", "dist1", "account_age_days", "uid_prior_n", "uid_n_1h", "uid_n_24h", "amt_vs_uid", "uid_new_device", "device_uids_7d",
            "uid_prior_fraud", "email_anon", "rule_score"]
PATTERN_NAMES = {"account_takeover": "Account takeover", "card_testing": "Card testing on a new account", "mule_ring": "Mule ring (one device, many accounts)",
                 "repeat_offender": "Repeat offender", "friendly_fraud": "Friendly fraud (customer disputes a real payment)"}


def eda(df: pd.DataFrame, F: pd.DataFrame, y: np.ndarray, pattern: np.ndarray, te: np.ndarray, caught: np.ndarray) -> dict[str, Any]:
    """Exploratory analysis for the page: class balance, missing values, distributions by class, correlations, fraud patterns."""
    raw_cols = ["TransactionAmt", "ProductCD", "card4", "card6", "addr1", "dist1", "P_emaildomain", "D1", "DeviceType", "DeviceInfo", "id_30", "id_31"]
    missing = [{"column": c, "missing": round(float(df[c].isna().mean()), 4)} for c in raw_cols if c in df]
    vals = F.assign(amount=df["TransactionAmt"].to_numpy(float))
    hist = []
    for col, label, edges, labs in EDA_HIST:
        v = vals[col].to_numpy(float)
        b = pd.cut(v, edges, labels=labs, right=False)
        hist.append({"feature": col, "label": label, "missing_fraud": round(float(np.isnan(v[y == 1]).mean()), 4), "missing_genuine": round(float(np.isnan(v[y == 0]).mean()), 4),
                     "bins": [{"bin": k, "fraud": round(float(((b == k) & (y == 1)).sum() / max(1, (y == 1).sum())), 4),
                               "genuine": round(float(((b == k) & (y == 0)).sum() / max(1, (y == 0).sum())), 4)} for k in labs]})
    C = F[EDA_CORR].assign(is_fraud=y).astype(float).corr().round(3)
    pats = []
    fr = y == 1
    for k, name in PATTERN_NAMES.items():
        m = fr & (pattern == k)
        mt = m[te]
        if not m.any():
            continue
        pats.append({"pattern": k, "name": name, "rows": int(m.sum()), "share": round(float(m.sum() / fr.sum()), 4),
                     "median_amount": round(float(np.median(df.loc[m, "TransactionAmt"])), 2),
                     "new_device": round(float(F.loc[m, "flag_new_device"].mean()), 3), "burst": round(float(F.loc[m, "flag_burst"].mean()), 3),
                     "night": round(float(F.loc[m, "flag_night"].mean()), 3), "far": round(float(F.loc[m, "flag_far"].mean()), 3),
                     "new_account": round(float(F.loc[m, "flag_new_account"].mean()), 3), "shared_device": round(float(F.loc[m, "flag_shared_device"].mean()), 3),
                     "anon_email": round(float(F.loc[m, "flag_anon_email"].mean()), 3), "prior_fraud": round(float((F.loc[m, "uid_prior_fraud"] > 0).mean()), 3),
                     "test_rows": int(mt.sum()), "caught": round(float(caught[te][mt].mean()), 3) if mt.any() else None})
    return {"rows": int(len(y)), "fraud": int(y.sum()), "genuine": int((y == 0).sum()), "columns": int(df.shape[1]), "missing": missing, "hist": hist,
            "corr": {"features": [ff.LABELS.get(c, c) for c in EDA_CORR] + ["is fraud"], "matrix": C.to_numpy().tolist()},
            "fraud_corr": sorted([{"feature": ff.LABELS.get(c, c), "r": float(C.loc[c, "is_fraud"])} for c in EDA_CORR], key=lambda d: -abs(d["r"])),
            "patterns": pats}


def real_check() -> dict[str, Any] | None:
    """Compact summary of the frozen real-data run, shown as a side check next to the synthetic results."""
    if not REAL_JSON.exists():
        return None
    r = json.loads(REAL_JSON.read_text())["ieee"]
    return {"rows": r["rows"], "test_rows": r["test_rows"], "base_rate_test": r["base_rate_test"], "best": r["best"], "triage": r.get("triage"),
            "models": {k: {"name": v["name"], "test": v["test"], "at_threshold": {a: v["at_threshold"][a] for a in ("precision", "recall", "f1")}} for k, v in r["models"].items()}}


def run_synth() -> dict[str, Any]:
    t0 = time.time()
    cache = SYNTH / "_features.pkl"
    if cache.exists():
        df, F = pd.read_pickle(cache)
    else:
        df = ff.load_ieee(SYNTH)
        F = ff.build(df)
        pd.to_pickle((df, F), cache)
    pattern = pd.read_csv(SYNTH / "_patterns.csv").set_index("TransactionID").loc[df["TransactionID"], "pattern"].to_numpy()
    y = df["isFraud"].to_numpy(int)
    amt = df["TransactionAmt"].to_numpy(float)
    period = np.minimum(df["TransactionDT"].to_numpy() // (30 * ff.DAY), 5).astype(int)
    print(f"features ready in {time.time() - t0:.0f}s: {F.shape}", flush=True)
    dnum, dcat = ff.DEPLOY_NUM, ff.DEPLOY_CAT
    dep = experiment("Synthetic data (IEEE-CIS layout, merchant/gateway fields)", F, y, period, amt, dnum, dcat, 4, 5, [2, 3, 4, 5], None, SYNTH_MODELS,
                     thr_mode="f1", preset_targets=(0.95, 0.95))
    dep["synthetic"] = True
    tree = "xgb"
    dep["explainer"] = tree
    tr, va, te = dep["_split"]
    te_idx = np.flatnonzero(te)
    samp = np.random.default_rng(SEED).choice(te_idx, min(20000, len(te_idx)), replace=False)
    imp = contributions(dep["_fitted"][tree]["pipeline"], F.loc[samp], dnum, dcat).abs().mean().sort_values(ascending=False)
    dep["importance"] = [{"feature": k, "label": ff.LABELS.get(k, k), "mean_abs_shap": round(float(v), 4)} for k, v in imp.items()]
    dep["learning_curve"] = learning_curve(F, y, tr, te, dep["best"], dnum, dcat)

    best = dep["_fitted"][dep["best"]]
    ct, thr = best["_ct"], best["threshold"]
    rng = np.random.default_rng(7)
    pick = lambda m, k: list(rng.choice(te_idx[m], min(k, int(m.sum())), replace=False))  # noqa: E731
    cases = {"caught_fraud": pick((y[te] == 1) & (ct >= thr) & (F.loc[te, "uid_prior_n"].to_numpy() > 0), 3), "missed_fraud": pick((y[te] == 1) & (ct < thr), 2),
             "genuine": pick((y[te] == 0) & (ct < thr * 0.3) & (F.loc[te, "uid_prior_n"].to_numpy() > 2), 3), "false_alarm": pick((y[te] == 0) & (ct >= thr), 2)}
    dep["examples"] = [{"kind": k, "transaction_id": int(df.loc[i, "TransactionID"]), "actual_fraud": int(y[i]), "pattern": str(pattern[i]),
                        "inputs": example_inputs(F, i, float(amt[i]))} for k, ids in cases.items() for i in ids]
    caught = np.zeros(len(y), bool)
    caught[te_idx] = ct >= thr

    version = time.strftime("v%Y.%m.%d-%H%M") + "-synth"
    meta = {"version": version, "best": dep["best"], "best_name": NAMES[dep["best"]], "explainer": tree,
            "dataset": "SYNTHETIC payments in the IEEE-CIS layout (ml/make_synthetic_ieee.py)", "train_window": "days 0-119 (all fraud + 25% of genuine)",
            "calibration_window": "days 120-149", "test_window": "days 150-182", "train_rows": dep["train_rows"], "features": dnum + dcat, "git_commit": git_commit(),
            "test": dep["models"][dep["best"]]["test"], "presets": {k: v["threshold"] for k, v in dep["presets"].items()}, "review_cost": REVIEW_COST,
            "trained_at": time.strftime("%Y-%m-%d %H:%M")}
    joblib.dump({"models": {m: {k: v for k, v in f.items() if not k.startswith("_")} for m, f in dep["_fitted"].items()}, "num": dnum, "cat": dcat, "meta": meta}, MODEL_PATH, compress=3)
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []
    reg.append({**meta, "artifact": str(MODEL_PATH.relative_to(BACKEND)).replace("\\", "/")})
    REGISTRY.write_text(json.dumps(reg, indent=2))
    dep["registry"] = meta
    return {"ieee": strip(dep), "insights": data_insights(df, F, y), "eda": eda(df, F, y, pattern, te, caught), "real_check": real_check()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", choices=["synth", "real"], default="synth")
    ap.add_argument("--skip-ulb", action="store_true")
    a = ap.parse_args()
    out: dict[str, Any] = {"generated": time.strftime("%Y-%m-%d %H:%M"), "review_cost": REVIEW_COST, "synthetic": a.data == "synth"}
    if a.data == "synth":
        global WF_CACHE
        WF_CACHE = SYNTH / "_walk_forward.json"
        out.update(run_synth())
    else:
        out.update(run_ieee())
    if a.data == "real" and not a.skip_ulb and (r := run_ulb()):
        out.update(r)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(f"\nwrote {OUT_JSON} ({OUT_JSON.stat().st_size // 1024} kB) and {MODEL_PATH}")


if __name__ == "__main__":
    main()
