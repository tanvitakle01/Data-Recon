"""Coverage for the value-pair library management routes: list, delete, and
the confirm-gated flush — mirrors test coverage of the attribute-mapping
library routes (routes/library.py).
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
    assert pairs[0]["source_value"] == "5006"
    assert pairs[0]["target_value"] == "PL5006"


def test_delete_removes_a_pair(client):
    pair = _propose()
    res = client.delete(f"/api/recon/value-pairs/{pair.id}")
    assert res.status_code == 200, res.text
    assert client.get("/api/recon/value-pairs").json()["pairs"] == []


def test_delete_unknown_pair_404s(client):
    res = client.delete("/api/recon/value-pairs/nope")
    assert res.status_code == 404


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
