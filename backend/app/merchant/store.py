"""In-memory dataset registry. Nothing is written to disk and nothing survives a restart.

* 'sample' is built on first use and cached.
* Uploads get an unguessable id (a bearer capability: whoever holds it can read that dataset, nobody else can),
  expire after TTL, and the registry keeps at most MAX_UPLOADS (oldest evicted).
There are no user accounts in this project, so isolation between merchants rests on those ids.
"""

from __future__ import annotations

import io
import pickle
import secrets
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd

from . import risk
from .model import (MAX_ROWS, MerchantDataset, UploadError, empty_orders, empty_refunds, empty_settlements, parse_orders, parse_refunds, parse_settlements, parse_transactions)
from .actions import build_actions
from .analytics import unusual_days
from .reconcile import reconcile
from .sample import build_sample

TTL_SECONDS = 2 * 3600
MAX_UPLOADS = 10
MAX_BYTES = 8 * 1024 * 1024

_lock = threading.Lock()
_sets: dict[str, tuple[float, MerchantDataset]] = {}
_sample: MerchantDataset | None = None
_model: dict[str, Any] | None = None
_model_loaded = False


def analyze(ds: MerchantDataset) -> MerchantDataset:
    global _model, _model_loaded
    if not _model_loaded:
        _model, _model_loaded = risk.load_model(), True
    ds.discrepancies = reconcile(ds)
    if "zone" in ds.transactions and ds.transactions["zone"].notna().all():
        risk.assess_scored(ds)
    else:
        risk.assess(ds, _model)
    ds.unusual = unusual_days(ds)
    ds.actions = build_actions(ds)
    return ds


def reset_model_cache() -> None:  # tests
    global _model_loaded
    _model_loaded = False


CACHE = Path(__file__).resolve().parents[2] / "data" / "merchant_sample" / "_analyzed.pkl"


def _signature() -> str:
    """Changes when the sample CSV or any code that shapes the analysed dataset changes, so a stale cache is never used."""
    parts = [CACHE.parent / "transactions.csv", *(Path(__file__).with_name(f) for f in ("sample.py", "model.py", "reconcile.py", "risk.py", "actions.py", "analytics.py", "store.py"))]
    return "|".join(f"{p.name}:{int(p.stat().st_mtime)}:{p.stat().st_size}" if p.exists() else f"{p.name}:none" for p in parts)


def _cached_sample() -> MerchantDataset | None:
    try:
        sig, ds = pickle.loads(CACHE.read_bytes())
        return ds if sig == _signature() else None
    except Exception:  # noqa: BLE001 - a missing or broken cache just means a rebuild
        return None


def get_sample() -> MerchantDataset:
    """The sample business. Building and analysing it takes about half a minute, so the result is cached on disk."""
    global _sample
    with _lock:
        if _sample is None:
            _sample = _cached_sample()
            if _sample is None:
                _sample = analyze(build_sample())
                try:
                    CACHE.write_bytes(pickle.dumps((_signature(), _sample), protocol=pickle.HIGHEST_PROTOCOL))
                except OSError:
                    pass  # read-only disk: fine, just no cache
        return _sample


def get(ds_id: str) -> MerchantDataset | None:
    if ds_id == "sample":
        return get_sample()
    now = time.time()
    with _lock:
        for k in [k for k, (t, _) in _sets.items() if now - t > TTL_SECONDS]:
            del _sets[k]
        hit = _sets.get(ds_id)
        return hit[1] if hit else None


def delete(ds_id: str) -> bool:
    with _lock:
        return _sets.pop(ds_id, None) is not None


def _read(raw: bytes, name: str) -> pd.DataFrame:
    if len(raw) > MAX_BYTES:
        raise UploadError(f"The {name} file is larger than {MAX_BYTES // 1024 // 1024} MB.")
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, na_values=["", "NA", "N/A", "null", "None"], encoding_errors="replace")
    except Exception as e:  # noqa: BLE001
        raise UploadError(f"Could not read the {name} file as CSV ({type(e).__name__}).") from e
    if len(df) > MAX_ROWS:
        raise UploadError(f"The {name} file has more than {MAX_ROWS:,} rows.")
    return df


def create_upload(transactions: bytes, orders: bytes | None = None, refunds: bytes | None = None, settlements: bytes | None = None, label: str = "Your uploaded data") -> tuple[str, MerchantDataset]:
    tx, w = parse_transactions(_read(transactions, "transactions"))
    warnings = list(w)
    o, r, s = empty_orders(), empty_refunds(), empty_settlements()
    for raw, name, parse in ((orders, "orders", parse_orders), (refunds, "refunds", parse_refunds), (settlements, "settlements", parse_settlements)):
        if raw:
            frame, notes = parse(_read(raw, name))
            warnings += notes
            o, r, s = (frame if name == "orders" else o), (frame if name == "refunds" else r), (frame if name == "settlements" else s)
    ds = MerchantDataset(
        transactions=tx, orders=o, refunds=r, settlements=s, source="upload", label=label, warnings=warnings,
        notes=["This is the data you uploaded, processed in memory on this server and discarded after 2 hours or on restart. It is not stored.",
               "Reconciliation only covers the files you provided. Nothing is verified against a bank or payment provider."],
    )
    if tx["label_fraud"].notna().any():
        ds.fraud_labels = tx["label_fraud"]
    analyze(ds)
    ds_id = "u-" + secrets.token_urlsafe(16)
    with _lock:
        while len(_sets) >= MAX_UPLOADS:
            del _sets[min(_sets, key=lambda k: _sets[k][0])]
        _sets[ds_id] = (time.time(), ds)
    return ds_id, ds
