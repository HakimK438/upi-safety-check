"""UPI Safety Check API.

No accounts and no login. Nothing a merchant uploads is written to disk: datasets live in memory (see merchant/store.py)
and expire after two hours. The only thing persisted is the Fraud / Fine marks given to flagged payments, kept for the next retrain.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .merchant.fraud_api import router as fraud_router
from .merchant.router import router as merchant_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("MERCHANT_WARM") != "0":  # build the sample business now so the dashboard opens instantly
        from .merchant import store

        def warm() -> None:
            try:
                store.get_sample()
            except Exception as e:  # noqa: BLE001 - never block startup
                print("sample warm-up skipped:", e)

        threading.Thread(target=warm, daemon=True, name="warm-merchant").start()
    yield


app = FastAPI(title="UPI Safety Check API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173").split(","),
    allow_origin_regex=os.environ.get("CORS_ORIGIN_REGEX") or None,  # e.g. https://.*\.vercel\.app
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(merchant_router)
app.include_router(fraud_router)

# --- tiny in-memory rate limiter (per IP, per minute) -------------------------- #
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
LIMITS = {"/api/merchant/datasets": 10}


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    path = request.url.path
    limit = LIMITS.get(path, 240)
    key = (request.client.host if request.client else "?", path)
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit and os.environ.get("DISABLE_RATE_LIMIT") != "1":
        return JSONResponse({"error": "rate_limited", "message": "Too many requests, try again in a minute."}, status_code=429)
    q.append(now)
    return await call_next(request)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "database": "ok"}
