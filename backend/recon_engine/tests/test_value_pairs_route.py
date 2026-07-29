"""Coverage for the value-pair library management routes: list, approve,
reject, delete, and the confirm-gated flush — mirrors test coverage of the
attribute-mapping library routes (routes/library.py).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recon_engine.storage import value_pair_store
from backend.routes.value_pairs import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _propose():
    return value_pair_store.propose(
        source_connector="s4",
        target_connector="ibp",
        source_field="Material",
        target_field="PRDID",
        source_value="5006",
        target_value="PL5006",
        ops=[{"op": "prepend_prefix", "params": {"value": "PL"}}],
    )


def test_list_value_pairs_returns_proposed_rows(client):
    _propose()
    res = client.get("/api/recon/value-pairs")
    assert res.status_code == 200, res.text
    pairs = res.json()["pairs"]
    assert len(pairs) == 1
    assert pairs[0]["status"] == "pending"


def test_approve_marks_the_pair_approved(client):
    pair = _propose()
    res = client.post(f"/api/recon/value-pairs/{pair.id}/approve", params={"actor": "reviewer"})
    assert res.status_code == 200, res.text
    assert res.json()["pair"]["status"] == "approved"
    assert res.json()["pair"]["reviewed_by"] == "reviewer"


def test_reject_records_a_reason(client):
    pair = _propose()
    res = client.post(
        f"/api/recon/value-pairs/{pair.id}/reject",
        params={"actor": "reviewer", "reason": "wrong transform"},
    )
    assert res.status_code == 200, res.text
    body = res.json()["pair"]
    assert body["status"] == "rejected"
    assert body["evidence"]["rejection_reason"] == "wrong transform"


def test_approve_unknown_pair_404s(client):
    res = client.post("/api/recon/value-pairs/nope/approve")
    assert res.status_code == 404


def test_delete_removes_a_pair(client):
    pair = _propose()
    res = client.delete(f"/api/recon/value-pairs/{pair.id}")
    assert res.status_code == 200, res.text
    assert client.get("/api/recon/value-pairs").json()["pairs"] == []


def test_flush_requires_confirm(client):
    _propose()
    res = client.post("/api/recon/value-pairs/flush")
    assert res.status_code == 400
    assert len(client.get("/api/recon/value-pairs").json()["pairs"]) == 1


def test_flush_with_confirm_empties_the_library(client):
    _propose()
    res = client.post("/api/recon/value-pairs/flush", params={"confirm": "true"})
    assert res.status_code == 200, res.text
    assert res.json()["flushed"] == 1
    assert client.get("/api/recon/value-pairs").json()["pairs"] == []
