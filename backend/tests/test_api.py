"""App wiring: health, CORS and the rate limiter."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_removed_consumer_endpoints_are_gone(client):
    for path in ("/api/triage", "/api/extract", "/api/numbers/check", "/api/reference/handles"):
        assert client.get(path).status_code in (404, 405)
