"""Build the Dashboard's sample business from the SYNTHETIC IEEE-layout data (the data the four fraud models were built on).

Run from backend/:  python ml/make_merchant_sample.py

Only the TEST period (days 150-182) is used: the models never saw it. Every payment is scored by the shipped XGBoost
model and put in a zone (Safe / Check / Fraud) with the same cut-offs as the Fraud check page. One row in ten is kept
(seeded), so the fraud rate stays ~3.5% and the Dashboard stays quick. Output: data/merchant_sample/transactions.csv
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.merchant import fraud_features as ff  # noqa: E402

SYNTH = BACKEND / "data"
OUT = BACKEND / "data" / "merchant_sample" / "transactions.csv"
RESULTS = BACKEND.parent / "docs" / "ml" / "fraud_results.json"
INR_PER_USD = 88  # same fixed rate as the Fraud check page
START = pd.Timestamp("2024-07-01")  # day 0 of the synthetic data, shown as a calendar date
N_BRANCHES = 12
SEED = 11

REASONS = [("flag_new_device", "the payment came from a phone this customer has not used before"),
           ("flag_burst", "the customer made several payments within the last hour"),
           ("flag_amount_spike", "the amount is far above what this customer usually pays"),
           ("flag_shared_device", "the same device was used by several different accounts"),
           ("flag_new_account", "the customer's account is only a few days old"),
           ("flag_anon_email", "the email or UPI handle is anonymous"),
           ("flag_far", "the payment came from far away from the customer's usual place"),
           ("flag_night", "the payment was made late at night")]


def main() -> None:
    df, F = pd.read_pickle(SYNTH / "_features.pkl")
    bundle = joblib.load(BACKEND / "models" / "fraud_models.joblib")
    tri = json.loads(RESULTS.read_text())["ieee"]["triage"]
    check, block = tri["check_threshold"], tri["block_threshold"]
    best = bundle["meta"]["best"]
    m = bundle["models"][best]

    day = df["TransactionDT"].to_numpy() // ff.DAY
    rng = np.random.default_rng(SEED)
    keep = np.flatnonzero((day >= 150) & (rng.random(len(df)) < 0.10))
    d, f = df.iloc[keep].reset_index(drop=True), F.iloc[keep].reset_index(drop=True)
    X = f[bundle["num"] + bundle["cat"]]
    prob = m["calibrator"].predict(m["pipeline"].predict_proba(X)[:, 1])
    zone = np.where(prob >= block, "fraud", np.where(prob >= check, "check", "safe"))

    reasons = ["|".join(t for c, t in REASONS if f.at[i, c] > 0) for i in range(len(f))]
    y = d["isFraud"].to_numpy(int)
    u = rng.random(len(d))
    # Payment status: most go through; a few fail or stay pending; confirmed fraud ends as a reversal (chargeback).
    status = np.where(y == 1, np.where(u < 0.7, "reversed", "success"), np.where(u < 0.955, "success", np.where(u < 0.985, "failed", np.where(u < 0.997, "pending", "reversed"))))
    region = d["addr1"].fillna(-1).astype(int).to_numpy()
    out = pd.DataFrame({
        "txn_ref": (600_000_000_000 + d["TransactionID"].astype("int64")).astype(str), "timestamp": START + pd.to_timedelta(d["TransactionDT"], unit="s"),
        "amount": (d["TransactionAmt"].to_numpy(float) * INR_PER_USD).round(2), "status": status,
        "outlet": ["Outlet %02d" % (1 + r % N_BRANCHES) for r in region],
        "payer_ref": ("C" + d["card1"].astype(int).astype(str)).to_numpy(), "is_fraud": y, "fraud_prob": prob.round(5), "zone": zone, "reasons": reasons,
    })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"wrote {len(out):,} payments to {OUT}  | fraud {y.mean():.2%} | zones {pd.Series(zone).value_counts().to_dict()} | {out.timestamp.min()} .. {out.timestamp.max()}")


if __name__ == "__main__":
    main()
