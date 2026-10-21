"""Spam-message lab: three NLP classifiers (TF-IDF features) compared on one held-out split of the SMS spam dataset.

Trains lazily on the first request (a few seconds), then stays in memory. The dataset is English SMS spam, not UPI-specific,
so results are a teaching comparison and a second opinion, never a guarantee that a message is safe.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import LinearSVC

DATA = Path(__file__).resolve().parents[2] / "data"
CSV = DATA / "spam.csv"  # English SMS spam
INDIA_CSV = DATA / "shade63" / "sentinel_dataset_multiclass.csv"  # Indian bank / UPI / government scam texts (optional, not in the repository: no licence)


def _template(text: str) -> str:
    """Same message with the numbers masked. Messages sharing a template must stay on one side of the split, or the test leaks."""
    return re.sub(r"\d+", "0", re.sub(r"\s+", " ", text.lower())).strip()


def _load() -> pd.DataFrame:
    eng = pd.read_csv(CSV, encoding="latin-1").iloc[:, :2]
    eng.columns = ["label", "text"]
    eng["label"] = (eng["label"] == "spam").astype(int)
    eng["source"] = "english"
    frames = [eng]
    if INDIA_CSV.exists():
        ind = pd.read_csv(INDIA_CSV)[["text", "label"]]
        ind["label"] = (ind["label"] > 0).astype(int)
        ind["source"] = "india"
        frames.append(ind)
    df = pd.concat(frames, ignore_index=True).dropna(subset=["text", "label"])
    df["tpl"] = df["text"].map(_template)
    return df.drop_duplicates("tpl")
NAMES = {"nb": "Naive Bayes", "logreg": "Logistic regression", "svm": "Linear SVM"}
ABOUT = {
    "nb": "Counts how often each word shows up in spam versus normal texts. Fast and a classic for text.",
    "logreg": "Gives every word a weight toward spam or normal and adds them up. Easy to explain.",
    "svm": "Finds the cleanest dividing line between spam and normal texts. Often the sharpest on text.",
}
FLAGS = [  # plain-language warning signs, matched by regex (a second layer next to the models)
    ("link", r"https?://|www\.|\b\w+\.(?:com|in|xyz|top|co)\b|bit\.ly", "Contains a link. Do not tap links in unexpected messages."),
    ("urgent", r"\b(urgent|immediately|expire[sd]?|last chance|within \d+ ?(?:hours?|hrs?|mins?)|blocked|suspend)", "Pushes you to act in a hurry."),
    ("money", r"\b(won|winner|prize|reward|cashback|refund|lottery|claim|free)\b|£|\$|rs\.? ?\d|₹", "Promises money or a prize."),
    ("secret", r"\b(otp|pin|cvv|password|kyc|aadhaar|pan)\b", "Asks for a code, PIN or personal ID. Real banks never do."),
    ("call", r"\b(call|ring|reply|text|send)\b.{0,20}\b\d{5,}", "Asks you to call or reply to a number."),
]


class _State:
    lock = threading.Lock()
    ready = False
    vec: TfidfVectorizer
    models: dict[str, Any]
    results: list[dict[str, Any]]
    info: dict[str, Any]
    best: str


PARAMS: dict[str, list[tuple[str, str, str]]] = {
    "nb": [("Algorithm", "Multinomial Naive Bayes", "Counts how often each word appears in spam vs normal texts"), ("Smoothing (alpha)", "0.1", "Stops unseen words from breaking the maths")],
    "logreg": [("Algorithm", "Logistic regression", "One weight per word, added up into a spam score"), ("Regularisation (C)", "10", "Higher value lets word weights grow larger"), ("Class weight", "Balanced", "Spam counts more because it is rarer"), ("Max iterations", "2,000", "Upper limit on training steps")],
    "svm": [("Algorithm", "Linear SVM (calibrated)", "Finds the cleanest dividing line between spam and normal"), ("Regularisation (C)", "1", "Balance between a clean line and a few mistakes"), ("Class weight", "Balanced", "Spam counts more because it is rarer"), ("Calibration", "3-fold", "Turns raw distances into a 0 to 100% score")],
}
S = _State()


def _prob(m: Any, X: Any) -> np.ndarray:
    return np.asarray(m.predict_proba(X)[:, 1])


def _top_words(mid: str, m: Any, k: int = 8) -> list[dict[str, Any]]:
    """The words each model leans on most to call a message a scam, as 0-1 weights (the strongest word = 1)."""
    names = S.vec.get_feature_names_out()
    if mid == "nb":
        w = m.feature_log_prob_[1] - m.feature_log_prob_[0]
    elif mid == "logreg":
        w = m.coef_[0]
    else:  # calibrated linear SVM: average the coefficients of its calibrated copies
        w = np.mean([c.estimator.coef_[0] for c in m.calibrated_classifiers_], axis=0)
    idx = np.argsort(w)[::-1][:k]
    top = float(w[idx[0]]) or 1.0
    return [{"word": str(names[i]), "weight": round(float(w[i]) / top, 3)} for i in idx]


def _train() -> None:
    df = _load()  # one row per message template: near-copies would leak between train and test
    y = df["label"].astype(int).to_numpy()
    tr, te = next(GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=0).split(df, y, groups=df["tpl"]))
    xtr_t, xte_t, ytr, yte = df["text"].iloc[tr], df["text"].iloc[te], y[tr], y[te]
    S.vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=2, sublinear_tf=True, stop_words="english")
    xtr, xte = S.vec.fit_transform(xtr_t), S.vec.transform(xte_t)
    S.models = {
        "nb": MultinomialNB(alpha=0.1).fit(xtr, ytr),
        "logreg": LogisticRegression(C=10, max_iter=2000, class_weight="balanced").fit(xtr, ytr),
        "svm": CalibratedClassifierCV(LinearSVC(C=1, class_weight="balanced"), cv=3).fit(xtr, ytr),
    }
    S.results = []
    for mid, m in S.models.items():
        p = _prob(m, xte)
        pred = p >= 0.5
        tn, fp, fn, tp = confusion_matrix(yte, pred, labels=[0, 1]).ravel()
        S.results.append({
            "top_words": _top_words(mid, m),
            "id": mid, "name": NAMES[mid], "about": ABOUT[mid], "params": PARAMS[mid], "accuracy": float(accuracy_score(yte, pred)), "precision": float(precision_score(yte, pred, zero_division=0)),
            "recall": float(recall_score(yte, pred)), "f1": float(f1_score(yte, pred)), "roc_auc": float(roc_auc_score(yte, p)), "confusion": {"tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)},
        })
    S.best = max(S.results, key=lambda r: r["f1"])["id"]
    for r in S.results:
        r["best"] = r["id"] == S.best
    S.info = {
        "messages": int(len(df)), "spam": int(y.sum()), "spam_rate": float(y.mean()), "train": int(len(ytr)), "test": int(len(yte)), "test_spam": int(yte.sum()),
        "source": "Indian bank, UPI and government scam texts + English SMS spam (near-duplicates removed)", "vocab": int(len(S.vec.vocabulary_)), "threshold": 0.5,
        "split": "75% to learn, 25% to test; copies of the same message template never sit on both sides",
        "text_prep": "Words and word pairs, common English words removed, rare words weighted higher (TF-IDF)",
        "caveats": [
            "Tested on 25% of messages the models never saw. Near-identical messages (same text, different numbers) were merged first so nothing is memorised.",
            "Much of the Indian scam data is machine-generated from templates, so real-world accuracy will be lower than these scores. Use it as a second opinion next to your own judgement.",
        ],
    }
    S.ready = True


def ensure() -> None:
    if not S.ready:
        with S.lock:
            if not S.ready:
                _train()


def summary() -> dict[str, Any]:
    ensure()
    return {"info": S.info, "models": S.results, "best": S.best}


def _triggers(model_id: str, text: str, limit: int = 6) -> list[str]:
    """Words in this message that push the chosen model toward 'spam'."""
    m = S.models[model_id]
    x = S.vec.transform([text])
    if model_id == "nb":
        w = m.feature_log_prob_[1] - m.feature_log_prob_[0]
    elif model_id == "logreg":
        w = m.coef_[0]
    else:
        w = np.mean([c.estimator.coef_[0] for c in m.calibrated_classifiers_], axis=0)
    names = S.vec.get_feature_names_out()
    score = {int(i): float(w[i] * x[0, i]) for i in x.nonzero()[1]}
    return [str(names[i]) for i, s in sorted(score.items(), key=lambda kv: -kv[1])[:limit] if s > 0]


STEPS = {
    "spam": ["Do not tap any link or call any number in this message.", "Never share an OTP, PIN or card details.", "Delete it and block the sender. If you already acted, call 1930 (the cyber crime helpline) now."],
    "suspicious": ["Do not tap links. Check the sender through the official app or website.", "If it mentions a payment, confirm it in your own bank app, not through this message."],
    "ok": ["No scam pattern found. That is not a guarantee. Never share an OTP or PIN whatever a message says."],
}


def predict(text: str, model_id: str | None = None) -> dict[str, Any]:
    ensure()
    mid = model_id if model_id in S.models else S.best
    x = S.vec.transform([text])
    per = [{"id": k, "name": NAMES[k], "probability": round(float(_prob(m, x)[0]), 4)} for k, m in S.models.items()]
    p = next(r["probability"] for r in per if r["id"] == mid)
    flags = [{"id": i, "text": t} for i, rx, t in FLAGS if re.search(rx, text, re.I)]
    verdict = "spam" if p >= 0.7 else "suspicious" if p >= 0.35 or len(flags) >= 3 else "ok"
    return {
        "model": mid, "model_name": NAMES[mid], "probability": p, "verdict": verdict, "all_models": per, "agreement": sum(1 for r in per if r["probability"] >= 0.5),
        "triggers": _triggers(mid, text), "flags": flags, "next_steps": STEPS[verdict],
    }
