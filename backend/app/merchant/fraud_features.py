"""Features for the payment-fraud model, shared by training (ml/train_fraud.py) and live scoring (fraud_api.py).

Data: IEEE-CIS (Vesta) - REAL e-commerce card payments, labels are real chargebacks.
Every history feature for a payment uses ONLY earlier payments (no look-ahead); past fraud labels are used only after
LABEL_LAG, because a chargeback is confirmed weeks after the payment.

Two feature sets:
  DEPLOY   - fields a payment app / gateway actually gives a merchant (amount, time, payer id, device, OS, browser, email or
             handle domain, distance from usual place) + history computed from the merchant's own saved payments. Ships.
  RESEARCH - DEPLOY + Vesta's masked bank-side columns (C, D, M, V, id_*). Only to measure what hidden signals add.

The history features copy the patterns of real UPI / card fraud:
  account takeover (new device, new account), draining (burst, amount spike), mule/ring (many accounts on one device),
  throwaway identities (anonymous email), repeat offenders (earlier confirmed fraud).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DAY, HOUR = 86400, 3600
LABEL_LAG = 30 * DAY
ANON_EMAIL = {"anonymous.com", "protonmail.com", "mail.com", "guerrillamail.com", "yandex.ru", "mail.ru", "aim.com", "outlook.es"}
TOP_EMAIL = ["gmail.com", "yahoo.com", "hotmail.com", "anonymous.com", "aol.com", "comcast.net", "icloud.com", "outlook.com", "msn.com",
             "att.net", "live.com", "sbcglobal.net", "verizon.net", "ymail.com", "bellsouth.net"]

FLAGS = ["flag_new_device", "flag_burst", "flag_amount_spike", "flag_anon_email", "flag_new_account", "flag_shared_device", "flag_far", "flag_night"]
DEPLOY_NUM = ["log_amt", "cents", "hour", "dist1", "account_age_days", "uid_prior_n", "uid_gap_h", "uid_n_1h", "uid_n_24h", "amt_vs_uid",
              "uid_new_device", "uid_devices_seen", "device_uids_7d", "uid_prior_fraud", "email_anon", "email_missing", "has_device_info",
              *FLAGS, "rule_score"]
DEPLOY_CAT = ["ProductCD", "card4", "card6", "email", "DeviceType", "os", "browser"]
RESEARCH_EXTRA_NUM = [f"C{i}" for i in (1, 2, 5, 6, 9, 11, 13, 14)] + ["D2", "D3", "D4", "D10", "D11", "D15"] + \
                     [f"M{i}" for i in range(1, 10)] + ["id_01", "id_02", "id_05", "id_06", "id_13", "id_17", "id_19", "id_20"]

LABELS = {
    "log_amt": "payment amount", "cents": "odd paise/cents in the amount", "hour": "time of day", "dist1": "distance from the customer's usual place",
    "account_age_days": "age of the customer's account", "uid_prior_n": "customer's earlier payments", "uid_gap_h": "time since the customer's last payment",
    "uid_n_1h": "customer's payments in the last hour", "uid_n_24h": "customer's payments in the last 24 hours",
    "amt_vs_uid": "amount compared with the customer's usual amount", "uid_new_device": "first payment from this device",
    "uid_devices_seen": "number of devices this customer has used", "device_uids_7d": "different accounts paying from this device this week",
    "uid_prior_fraud": "earlier confirmed fraud on this account", "email_anon": "anonymous email / handle", "email_missing": "no email / handle given",
    "has_device_info": "device details available", "flag_new_device": "new device for this customer", "flag_burst": "burst of payments within an hour",
    "flag_amount_spike": "amount more than 3x usual", "flag_anon_email": "anonymous email / handle", "flag_new_account": "account less than a week old",
    "flag_shared_device": "device shared by 3+ accounts this week", "flag_far": "far from the usual place (>100 km)", "flag_night": "night-time (0-5 am)",
    "rule_score": "number of warning signs", "ProductCD": "product type", "card4": "card network", "card6": "debit or credit",
    "email": "email / handle domain", "DeviceType": "mobile or desktop", "os": "operating system", "browser": "browser",
}
# Plain-language reason shown to a merchant when a feature pushes risk UP.
REASON_UP = {
    "uid_new_device": "First payment from this device", "flag_new_device": "New device for this customer", "uid_n_1h": "Several payments within one hour",
    "flag_burst": "Burst of payments within an hour", "uid_n_24h": "Many payments in the last 24 hours", "amt_vs_uid": "Amount is far above this customer's usual",
    "flag_amount_spike": "Amount is more than 3x the usual", "email_anon": "Anonymous email / handle", "flag_anon_email": "Anonymous email / handle",
    "account_age_days": "Very new account", "flag_new_account": "Account is less than a week old", "device_uids_7d": "Several accounts used this device recently",
    "flag_shared_device": "Device shared by many accounts (possible mule / ring)", "dist1": "Far from the customer's usual place", "flag_far": "Far from the usual place",
    "uid_prior_fraud": "This account had confirmed fraud before", "hour": "Unusual time of day", "flag_night": "Night-time payment",
    "uid_prior_n": "New customer with no history", "log_amt": "Amount pattern seen in fraud", "cents": "Odd amount pattern", "ProductCD": "Product type often targeted by fraud",
    "card6": "Payment instrument often used in fraud", "card4": "Card network pattern", "email": "Email domain often seen in fraud", "os": "Device OS pattern",
    "browser": "Browser pattern", "DeviceType": "Device type pattern", "uid_gap_h": "Unusual gap since the last payment", "uid_devices_seen": "Customer switches devices often",
    "email_missing": "No email / handle given", "has_device_info": "Device details hidden", "rule_score": "Several warning signs together",
}


def _family(s: pd.Series, rules: list[tuple[str, str]]) -> pd.Series:
    low = s.fillna("").str.lower()
    out = pd.Series("unknown", index=s.index, dtype=object)
    for needle, name in reversed(rules):
        out[low.str.contains(needle, regex=False)] = name
    out[(low != "") & (out == "unknown")] = "other"
    return out


def load_ieee(raw: Path, v_cols: list[str] | None = None) -> pd.DataFrame:
    """Read only the columns we use from the two IEEE-CIS training files (V columns only if asked)."""
    keep = {"TransactionID", "isFraud", "TransactionDT", "TransactionAmt", "ProductCD", "card1", "card2", "card4", "card6", "addr1", "dist1",
            "P_emaildomain", "D1", *RESEARCH_EXTRA_NUM, *(v_cols or [])}
    t = pd.read_csv(raw / "train_transaction.csv", usecols=lambda c: c in keep)
    ident = pd.read_csv(raw / "train_identity.csv", usecols=["TransactionID", "DeviceType", "DeviceInfo", "id_01", "id_02", "id_05", "id_06", "id_13",
                                                               "id_17", "id_19", "id_20", "id_30", "id_31", "id_33"])
    df = t.merge(ident, on="TransactionID", how="left", suffixes=("", "_i"))
    for c in [c for c in df.columns if c.endswith("_i")]:
        df[c[:-2]] = df[c[:-2]].fillna(df[c])
        df = df.drop(columns=c)
    for i in range(1, 10):
        if f"M{i}" in df:
            df[f"M{i}"] = df[f"M{i}"].map({"T": 1.0, "F": 0.0, "M0": 0.0, "M1": 1.0, "M2": 2.0})
    num = df.select_dtypes("number").columns.drop(["TransactionID", "isFraud", "TransactionDT"])
    df[num] = df[num].astype("float32")
    return df.sort_values(["TransactionDT", "TransactionID"], kind="stable").reset_index(drop=True)


def _grouped_window(group: np.ndarray, ts: np.ndarray, vals: np.ndarray, window: float, lag: float = 0.0) -> np.ndarray:
    """Per row: sum of `vals` over EARLIER rows of the same group with ts in (t - window, t - lag]. Data must be time-sorted."""
    codes = pd.factorize(group)[0].astype(np.int64)
    order = np.lexsort((np.arange(len(ts)), ts, codes))
    big = float(ts.max() - ts.min() + window + 10)
    key = codes[order] * big + (ts[order] - ts.min())
    v = vals[order].astype(float)
    cs = np.concatenate([[0.0], np.cumsum(v)])
    pos = np.arange(len(key))
    hi = pos if lag == 0 else np.searchsorted(key, key - lag, side="right")
    lo = np.searchsorted(key, key - window, side="right")
    out = np.empty(len(ts))
    out[order] = cs[np.maximum(hi, lo)] - cs[lo]
    return out


def build(df: pd.DataFrame, with_research: bool = False) -> pd.DataFrame:
    """Model features for a time-sorted IEEE-CIS frame."""
    ts = df["TransactionDT"].to_numpy(float)
    amt = df["TransactionAmt"].to_numpy(float)
    day = np.floor(ts / DAY)
    f = pd.DataFrame(index=df.index)
    f["log_amt"] = np.log1p(amt)
    f["cents"] = np.round(amt - np.floor(amt), 3)
    f["hour"] = (ts // HOUR) % 24
    f["dist1"] = df["dist1"].to_numpy(float)
    f["account_age_days"] = df["D1"].to_numpy(float)
    for c in ("ProductCD", "card4", "card6", "DeviceType"):
        f[c] = df[c].astype(object).fillna("unknown").astype(str)
    em = df["P_emaildomain"].astype(object)
    f["email"] = np.where(em.isin(TOP_EMAIL), em, np.where(em.isna(), "missing", "other"))
    f["email_anon"] = em.isin(ANON_EMAIL).astype(float)
    f["email_missing"] = em.isna().astype(float)
    f["os"] = _family(df["id_30"].astype(object), [("windows", "Windows"), ("ios", "iOS"), ("android", "Android"), ("mac", "macOS"), ("linux", "Linux")])
    f["browser"] = _family(df["id_31"].astype(object), [("samsung", "Samsung"), ("chrome", "Chrome"), ("safari", "Safari"), ("firefox", "Firefox"), ("edge", "Edge"), ("ie ", "IE"), ("opera", "Opera")])
    f["has_device_info"] = df["DeviceInfo"].notna().astype(float)

    # rebuilt customer id: card + billing region + the day the account started (TransactionDay - D1)
    c1 = df["card1"].fillna(-1).astype(int).astype(str)  # missing values become "-1" so every row has a customer id
    a1 = df["addr1"].fillna(-1).astype(int).astype(str)
    uid = (c1 + "_" + a1 + "_" + (day - df["D1"].fillna(-999)).astype(int).astype(str)).to_numpy()
    dev = (df["DeviceInfo"].astype(object).fillna("?").astype(str) + "|" + df["id_30"].astype(object).fillna("?").astype(str) + "|"
           + df["id_31"].astype(object).fillna("?").astype(str) + "|" + df["id_33"].astype(object).fillna("?").astype(str)).to_numpy()
    dev_known = df["DeviceInfo"].notna().to_numpy()

    g = pd.Series(uid)
    prior = g.groupby(g).cumcount().to_numpy()
    f["uid_prior_n"] = prior
    prev_ts = pd.Series(ts).groupby(g).shift(1).to_numpy()
    f["uid_gap_h"] = (ts - prev_ts) / HOUR
    ones = np.ones(len(ts))
    f["uid_n_1h"] = _grouped_window(uid, ts, ones, HOUR)
    f["uid_n_24h"] = _grouped_window(uid, ts, ones, DAY)
    cs = pd.Series(amt).groupby(g).cumsum().to_numpy() - amt
    with np.errstate(invalid="ignore", divide="ignore"):
        f["amt_vs_uid"] = np.where(prior > 0, amt / (cs / np.maximum(prior, 1)), np.nan)
    pair_first = (pd.Series(dev).groupby([g, pd.Series(dev)]).cumcount().to_numpy() == 0) & dev_known
    f["uid_new_device"] = (pair_first & (prior > 0)).astype(float)
    f["uid_devices_seen"] = pd.Series(pair_first.astype(float)).groupby(g).cumsum().to_numpy() - pair_first
    pair_dev_first = (pd.Series(uid).groupby([pd.Series(dev), g]).cumcount().to_numpy() == 0) & dev_known
    f["device_uids_7d"] = np.where(dev_known, _grouped_window(dev, ts, pair_dev_first.astype(float), 7 * DAY), np.nan)
    y = df["isFraud"].to_numpy(float) if "isFraud" in df else np.zeros(len(ts))
    f["uid_prior_fraud"] = _grouped_window(uid, ts, y, 10_000 * DAY, lag=LABEL_LAG)

    add_flags(f)
    if with_research:
        for c in RESEARCH_EXTRA_NUM + [c for c in df.columns if c.startswith("V")]:
            f[c] = df[c].to_numpy(float)
    return f


def add_flags(f: pd.DataFrame) -> pd.DataFrame:
    """The yes/no warning signs (heuristics). Used as features and, summed, as the rule baseline."""
    f["flag_new_device"] = (f["uid_new_device"] > 0).astype(float)
    f["flag_burst"] = (f["uid_n_1h"] >= 2).astype(float)
    f["flag_amount_spike"] = (f["amt_vs_uid"] > 3).astype(float)
    f["flag_anon_email"] = (f["email_anon"] > 0).astype(float)
    f["flag_new_account"] = (f["account_age_days"] < 7).astype(float)
    f["flag_shared_device"] = (f["device_uids_7d"] >= 3).astype(float)
    f["flag_far"] = (f["dist1"] > 100).astype(float)
    f["flag_night"] = (f["hour"] < 6).astype(float)
    f["rule_score"] = f[FLAGS].sum(axis=1)
    return f


def from_inputs(p: dict) -> pd.DataFrame:
    """One feature row from what a merchant / gateway knows about a payment (live scoring)."""
    amt = float(p["amount"])
    prior = float(p.get("customer_prior_payments") or 0)
    usual = p.get("customer_usual_amount")
    em = (p.get("email_domain") or "").strip().lower() or None
    row = {
        "log_amt": np.log1p(amt), "cents": round(amt - np.floor(amt), 3), "hour": float(p.get("hour", 12)), "dist1": p.get("distance_km"),
        "account_age_days": p.get("account_age_days"), "ProductCD": p.get("product", "W"), "card4": p.get("network", "visa"), "card6": p.get("instrument", "debit"),
        "email": em if em in TOP_EMAIL else ("missing" if em is None else "other"), "email_anon": float(em in ANON_EMAIL), "email_missing": float(em is None),
        "DeviceType": p.get("device_type", "mobile"), "os": p.get("os", "Android"), "browser": p.get("browser", "Chrome"), "has_device_info": 1.0,
        "uid_prior_n": prior, "uid_gap_h": p.get("hours_since_last_payment") if prior > 0 else np.nan,
        "uid_n_1h": float(p.get("payments_last_hour") or 0), "uid_n_24h": float(p.get("payments_last_24h") or 0),
        "amt_vs_uid": (amt / float(usual)) if (prior > 0 and usual) else np.nan,
        "uid_new_device": float(bool(p.get("new_device")) and prior > 0), "uid_devices_seen": float(1 if p.get("devices_seen") is None else p["devices_seen"]),
        "device_uids_7d": float(p.get("accounts_on_device_7d") or 0), "uid_prior_fraud": float(p.get("prior_fraud") or 0),
    }
    f = pd.DataFrame([row])
    for c in ("dist1", "account_age_days", "uid_gap_h"):
        f[c] = pd.to_numeric(f[c], errors="coerce")
    return add_flags(f)
