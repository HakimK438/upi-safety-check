"""Merchant dataset: the tables every merchant feature reads, plus validation of user-supplied CSVs.

All money is stored as integer paise (decimal-safe: no float arithmetic on rupees).
Nothing here is persisted; datasets live in memory (see store.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import numpy as np
import pandas as pd

STATUSES = ("success", "failed", "pending", "reversed")
MAX_ROWS = 100_000

# Optional payer-side signals. A payment provider may supply them; a merchant's own books usually do not.
SIGNAL_NUM = ["sig_new_device", "sig_ip_mismatch", "sig_failed_attempts", "sig_loyalty", "sig_user_avg_value", "sig_recurring"]
SIGNAL_CAT = ["txn_type", "payment_app", "device_type", "kyc", "city_tier"]
SCORED_COLUMNS = ["fraud_prob", "zone", "reasons"]
TXN_COLUMNS = ["txn_ref", "ts", "amount_paise", "status", "outlet", "payer_ref", "order_id", *SIGNAL_NUM, *SIGNAL_CAT, "label_fraud"]

_STATUS_WORDS = {
    "success": "success", "successful": "success", "completed": "success", "paid": "success", "succeeded": "success",
    "failed": "failed", "failure": "failed", "declined": "failed", "unsuccessful": "failed",
    "pending": "pending", "processing": "pending", "in progress": "pending",
    "reversed": "reversed", "reversal": "reversed",
}


def to_paise(value: Any) -> int | None:
    """Rupees (any common text form) -> integer paise, rounded half-up. None if not a positive amount."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    s = re.sub(r"[₹,\s]|Rs\.?|INR", "", str(value), flags=re.I)
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite() or d <= 0:
        return None
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_dt(values: pd.Series) -> pd.Series:
    """Dates and times from a CSV column. ISO text (2024-03-05 10:00) is read as ISO; anything else is read day-first (India).

    `dayfirst=True` alone is wrong for ISO text: it swaps day and month or rejects the value.
    """
    out = pd.to_datetime(values, errors="coerce", format="ISO8601")
    rest = out.isna() & values.notna()
    if rest.any():
        out[rest] = pd.to_datetime(values[rest], errors="coerce", dayfirst=True, format="mixed")
    return out


def norm_status(value: Any) -> str | None:
    return _STATUS_WORDS.get(str(value).strip().lower())


@dataclass
class MerchantDataset:
    """The merchant's books. `orders`, `refunds` and `settlements` may be empty when not provided."""

    transactions: pd.DataFrame
    orders: pd.DataFrame
    refunds: pd.DataFrame
    settlements: pd.DataFrame
    source: str  # 'sample' | 'upload'
    label: str
    notes: list[str] = field(default_factory=list)  # honest provenance / limitation lines shown in the UI
    warnings: list[str] = field(default_factory=list)
    injected: list[dict[str, str]] = field(default_factory=list)  # sample only: known planted issues, used by tests
    fraud_labels: pd.Series | None = None  # sample only: dataset label, used for evaluation, never shown per transaction
    # filled after analysis
    discrepancies: list[dict[str, Any]] = field(default_factory=list)
    risk: pd.DataFrame | None = None
    risk_info: dict[str, Any] = field(default_factory=dict)
    unusual: list[dict[str, Any]] = field(default_factory=list)  # precomputed by store.analyze
    actions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def anchor(self) -> pd.Timestamp | None:
        """'Now' for this dataset: the latest timestamp it contains. Periods are relative to it."""
        return None if self.transactions.empty else self.transactions["ts"].max()

    @property
    def has_orders(self) -> bool:
        return not self.orders.empty

    @property
    def has_settlements(self) -> bool:
        return not self.settlements.empty


def empty_orders() -> pd.DataFrame:
    return pd.DataFrame({"order_id": pd.Series(dtype=str), "ts": pd.Series(dtype="datetime64[ns]"), "amount_paise": pd.Series(dtype="int64"), "outlet": pd.Series(dtype=str)})


def empty_refunds() -> pd.DataFrame:
    return pd.DataFrame({"refund_id": pd.Series(dtype=str), "txn_ref": pd.Series(dtype=str), "ts": pd.Series(dtype="datetime64[ns]"), "amount_paise": pd.Series(dtype="int64")})


def empty_settlements() -> pd.DataFrame:
    return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "amount_paise": pd.Series(dtype="int64")})


def finalize_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Sort, add missing optional columns, and give every row a unique `tid` (repeated refs get ~2, ~3 ...)."""
    df = df.copy()
    for c in TXN_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan if (c in SIGNAL_NUM or c == "label_fraud") else None
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values(["ts", "txn_ref"], kind="stable").reset_index(drop=True)
    seq = df.groupby("txn_ref").cumcount()
    df["tid"] = np.where(seq == 0, df["txn_ref"], df["txn_ref"] + "~" + (seq + 1).astype(str))
    df["is_dup_row"] = seq > 0
    scored = [c for c in SCORED_COLUMNS if c in df.columns]  # fraud-model output carried by the sample data
    return df[["tid", "is_dup_row", *TXN_COLUMNS, *scored]]


# --------------------------------------------------------------------------- #
# CSV upload validation
# --------------------------------------------------------------------------- #
class UploadError(ValueError):
    """The upload cannot be used; the message is shown to the user as is."""


ALIASES: dict[str, dict[str, list[str]]] = {
    "transactions": {
        "txn_ref": ["txn_ref", "transaction_id", "transaction_ref", "txn_id", "reference", "ref_no", "utr", "rrn"],
        "ts": ["timestamp", "ts", "datetime", "date_time", "time", "transaction_time"],
        "amount": ["amount", "amt", "amount_inr", "amount_rs", "txn_amount"],
        "status": ["status", "payment_status", "txn_status"],
        "order_id": ["order_id", "order", "order_ref", "order_no"],
        "outlet": ["outlet", "store", "branch", "location", "merchant_id", "receiver_id"],
        "payer_ref": ["payer_ref", "payer", "customer_id", "user_id", "payer_id"],
        "label_fraud": ["is_fraud", "fraud", "fraud_label", "is_fraudulent", "label"],
        "sig_new_device": ["new_device_flag", "new_device"],
        "sig_ip_mismatch": ["ip_location_mismatch", "ip_mismatch"],
        "sig_failed_attempts": ["failed_attempts_last_24h", "failed_attempts"],
        "sig_loyalty": ["user_loyalty_score", "loyalty_score"],
        "sig_user_avg_value": ["user_avg_txn_value", "payer_avg_txn_value"],
        "sig_recurring": ["recurring_payment_flag", "recurring"],
        "txn_type": ["transaction_type", "txn_type"],
        "payment_app": ["payment_app", "app"],
        "device_type": ["device_type", "device"],
        "kyc": ["user_kyc_status", "kyc_status", "kyc"],
        "city_tier": ["user_city_tier", "city_tier"],
    },
    "orders": {"order_id": ["order_id", "order", "order_no"], "ts": ["timestamp", "ts", "datetime", "created_at", "order_time"], "amount": ["amount", "order_amount", "total", "amount_inr"], "outlet": ["outlet", "store", "branch", "location"]},
    "refunds": {"refund_id": ["refund_id", "refund_ref", "id"], "txn_ref": ["txn_ref", "transaction_id", "original_txn_ref", "txn_id", "reference"], "ts": ["timestamp", "ts", "datetime", "refund_time"], "amount": ["amount", "refund_amount", "amount_inr"]},
    "settlements": {"date": ["date", "settlement_date", "settled_on", "timestamp"], "amount": ["amount", "settled_amount", "settlement_amount", "amount_inr"]},
}
REQUIRED = {"transactions": ["txn_ref", "ts", "amount", "status"], "orders": ["order_id", "ts", "amount"], "refunds": ["txn_ref", "ts", "amount"], "settlements": ["date", "amount"]}


def _canon(df: pd.DataFrame, table: str) -> pd.DataFrame:
    low = {re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_"): c for c in df.columns}
    out = pd.DataFrame(index=df.index)
    for canon, names in ALIASES[table].items():
        for n in names:
            if n in low:
                out[canon] = df[low[n]]
                break
    missing = [c for c in REQUIRED[table] if c not in out.columns]
    if missing:
        raise UploadError(f"The {table} file is missing required column(s): {', '.join(missing)}. Columns found: {', '.join(map(str, df.columns))[:200]}.")
    return out


def _drop_bad(df: pd.DataFrame, table: str, checks: list[tuple[str, pd.Series]]) -> tuple[pd.DataFrame, list[str]]:
    """Drop invalid rows, keep a short reason list so nothing is silently discarded."""
    bad = pd.Series(False, index=df.index)
    reasons: list[str] = []
    for why, mask in checks:
        n = int((mask & ~bad).sum())
        if n:
            reasons.append(f"{n} {table} row(s) skipped: {why}")
        bad |= mask
    return df[~bad].copy(), reasons


def parse_transactions(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = _canon(raw, "transactions")
    df["ts"] = parse_dt(df["ts"])
    df["amount_paise"] = df["amount"].map(to_paise)
    df["status"] = df["status"].map(norm_status)
    df["txn_ref"] = df["txn_ref"].astype(str).str.strip()
    df, notes = _drop_bad(
        df, "transaction",
        [("unreadable date/time", df["ts"].isna()), ("amount missing, zero, negative or unreadable", df["amount_paise"].isna()),
         ("status is not success/failed/pending/reversed (or a common synonym)", df["status"].isna()), ("empty transaction reference", df["txn_ref"].isin(["", "nan", "None"]))],
    )
    if df.empty:
        raise UploadError("No valid transaction rows were found. " + " ".join(notes))
    df["amount_paise"] = df["amount_paise"].astype("int64")
    for c in ("order_id", "payer_ref"):
        if c in df:
            df[c] = df[c].map(lambda v: None if pd.isna(v) else (str(v).strip() or None))
    df["outlet"] = df["outlet"].fillna("Main").astype(str) if "outlet" in df else "Main"
    for c in SIGNAL_NUM:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "label_fraud" in df:
        yes = {"1", "true", "yes", "y", "fraud"}
        no = {"0", "false", "no", "n", "genuine", "ok", "legit"}
        v = df["label_fraud"].astype(str).str.strip().str.lower()
        df["label_fraud"] = np.where(v.isin(yes), 1.0, np.where(v.isin(no), 0.0, np.nan))
    return finalize_transactions(df.drop(columns=["amount"])), notes


def parse_orders(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = _canon(raw, "orders")
    df["ts"] = parse_dt(df["ts"])
    df["amount_paise"] = df["amount"].map(to_paise)
    df["order_id"] = df["order_id"].astype(str).str.strip()
    df, notes = _drop_bad(df, "order", [("unreadable date/time", df["ts"].isna()), ("amount missing or not positive", df["amount_paise"].isna()), ("empty order id", df["order_id"].isin(["", "nan", "None"]))])
    df["amount_paise"] = df["amount_paise"].astype("int64")
    df["outlet"] = df["outlet"].fillna("Main").astype(str) if "outlet" in df else "Main"
    dup = df["order_id"].duplicated(keep="first")
    if dup.any():
        notes.append(f"{int(dup.sum())} repeated order id(s) ignored (first one kept).")
    return df[~dup][["order_id", "ts", "amount_paise", "outlet"]].reset_index(drop=True), notes


def parse_refunds(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = _canon(raw, "refunds")
    df["ts"] = parse_dt(df["ts"])
    df["amount_paise"] = df["amount"].map(to_paise)
    df["txn_ref"] = df["txn_ref"].astype(str).str.strip()
    if "refund_id" not in df:
        df["refund_id"] = [f"RF{i + 1:05d}" for i in range(len(df))]
    df, notes = _drop_bad(df, "refund", [("unreadable date/time", df["ts"].isna()), ("amount missing or not positive", df["amount_paise"].isna())])
    df["amount_paise"] = df["amount_paise"].astype("int64")
    return df[["refund_id", "txn_ref", "ts", "amount_paise"]].reset_index(drop=True), notes


def parse_settlements(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = _canon(raw, "settlements")
    df["date"] = parse_dt(df["date"]).dt.normalize()
    df["amount_paise"] = df["amount"].map(to_paise)
    df, notes = _drop_bad(df, "settlement", [("unreadable date", df["date"].isna()), ("amount missing or not positive", df["amount_paise"].isna())])
    df["amount_paise"] = df["amount_paise"].astype("int64")
    # several settlement lines on one day are summed
    return df.groupby("date", as_index=False)["amount_paise"].sum(), notes
