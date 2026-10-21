"""Dashboard report: the numbers agree with each other and the slicers do what they say."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.merchant import dashboard, store

NONE = dict(date_from=None, date_to=None, branch=None, status=None, zone=None, hour=None, dow=None, day=None)


def _build(**kw):
    return dashboard.build(store.get_sample(), **{**NONE, **kw})


def test_default_window_is_last_30_days_and_waterfall_adds_up():
    r = _build()
    assert r["to"] == r["data_end"]
    assert (pd.Timestamp(r["to"]) - pd.Timestamp(r["from"])).days == 29
    w = r["waterfall"]
    assert w["sales"] - w["refunded"] - w["not_received"] + w["other"] == w["in_bank"]
    assert r["kpis"]["sales"]["value"] == w["sales"]
    assert sum(s["count"] for s in r["statuses"]) == r["payments_in_view"]
    assert sum(r["zones"].values()) == r["payments_in_view"]


def test_status_click_keeps_other_statuses_visible_but_filters_other_charts():
    all_ = _build()
    failed = _build(status="failed")
    assert failed["statuses"] == all_["statuses"]  # the status chart ignores its own slicer
    n_failed = next(s["count"] for s in all_["statuses"] if s["id"] == "failed")
    assert failed["payments_in_view"] == n_failed
    assert sum(failed["zones"].values()) == n_failed


def test_branch_and_day_slicers_narrow_the_numbers():
    all_ = _build()
    branch = all_["branches_all"][0]
    one = _build(branch=branch)
    assert one["kpis"]["sales"]["value"] <= all_["kpis"]["sales"]["value"]
    assert one["bank_basis"] == "payments"  # settlements are not split by branch
    day = _build(day="2024-12-20")
    assert day["from"] == day["to"] == "2024-12-20"
    assert len(day["series"]) == 1


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_endpoint(client):
    res = client.get("/api/merchant/sample/dashboard?status=failed&hour=9&dow=2")
    assert res.status_code == 200
    assert client.get("/api/merchant/sample/dashboard?status=bogus").status_code == 422
