"""Coverage for POST /api/recon/value-mapping/live-prepass — the merged
Mapping card's debounced, LLM-free pre-pass that keeps Mapping Review live as
the recipe changes. No LLM key is configured in these tests, so every case
resolves via the identity pre-pass, a stored library pair, or ends up
unpaired — never an LLM call (there is no LLM code path in this endpoint at
all, since it calls pair_values_deterministic_only, not pair_values).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recon_engine.storage import value_pair_store
from backend.routes.live_pairing import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _body(source_rows, target_rows, **extra):
    return {"source_rows": source_rows, "target_rows": target_rows, **extra}


def test_live_prepass_pairs_against_raw_values_with_no_recipe(client):
    source_rows = [{"Material": "MAT-1", "ProductionPlant": "PL01"}]
    target_rows = [{"PRDID": "MAT-1", "LOCID": "PL01"}]

    res = client.post("/api/recon/value-mapping/live-prepass", json=_body(source_rows, target_rows))
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["product"]["source_field"] == "Material"
    product_by_value = {m["source_value"]: m for m in body["product"]["matches"]}
    assert product_by_value["MAT-1"]["confidence"] == "very_high"
    assert product_by_value["MAT-1"]["rule"] == "value_pairing.identity"

    location_by_value = {m["source_value"]: m for m in body["location"]["matches"]}
    assert location_by_value["PL01"]["confidence"] == "very_high"


def test_live_prepass_pairs_against_recipe_transformed_values(client):
    # A transform step (uppercase) runs BEFORE pairing — the raw value "mat-1"
    # only resolves because the identity pre-pass sees the recipe's output
    # ("MAT-1"), not the raw source value.
    source_rows = [{"Material": "mat-1", "ProductionPlant": "PL01"}]
    target_rows = [{"PRDID": "MAT-1", "LOCID": "PL01"}]
    operations = [{"op": "uppercase", "field": "Material"}]

    res = client.post(
        "/api/recon/value-mapping/live-prepass",
        json=_body(source_rows, target_rows, operations=operations),
    )
    assert res.status_code == 200, res.text
    product_by_value = {m["source_value"]: m for m in res.json()["product"]["matches"]}
    assert product_by_value["MAT-1"]["confidence"] == "very_high"
    assert product_by_value["MAT-1"]["rule"] == "value_pairing.identity"


def test_live_prepass_reuses_a_stored_library_pair(client):
    value_pair_store.propose(
        source_connector="excel",
        target_connector="excel",
        source_field="Material",
        target_field="PRDID",
        source_value="5006",
        target_value="PL5006",
        ops=[{"op": "prepend_prefix", "params": {"value": "PL"}}],
    )
    source_rows = [{"Material": "5006", "ProductionPlant": "PL01"}]
    target_rows = [{"PRDID": "PL5006", "LOCID": "PL01"}]

    res = client.post("/api/recon/value-mapping/live-prepass", json=_body(source_rows, target_rows))
    assert res.status_code == 200, res.text
    product_by_value = {m["source_value"]: m for m in res.json()["product"]["matches"]}
    assert product_by_value["5006"]["confidence"] == "high"
    assert product_by_value["5006"]["rule"] == "value_pairing.library_reused"


def test_live_prepass_drops_aggregate_ops_before_pairing(client):
    # An aggregate op in the current recipe must never run ahead of pairing
    # (it changes row grain) — the endpoint silently filters it out, so
    # pairing still runs against the (unaggregated) recipe output.
    source_rows = [
        {"Material": "MAT-1", "ProductionPlant": "PL01", "Qty": 1},
        {"Material": "MAT-1", "ProductionPlant": "PL01", "Qty": 2},
    ]
    target_rows = [{"PRDID": "MAT-1", "LOCID": "PL01"}]
    operations = [{"op": "sum_aggregate", "field": "Qty", "params": {"by": ["Material"]}}]

    res = client.post(
        "/api/recon/value-mapping/live-prepass",
        json=_body(source_rows, target_rows, operations=operations),
    )
    assert res.status_code == 200, res.text
    product_by_value = {m["source_value"]: m for m in res.json()["product"]["matches"]}
    assert product_by_value["MAT-1"]["confidence"] == "very_high"


def test_live_prepass_leaves_unmatched_values_unpaired_never_calls_llm(client):
    # No LLM key configured anywhere in this test process, and this endpoint's
    # code path never imports/calls build_llm_client at all — a value with no
    # library/identity hit simply reports unpaired.
    source_rows = [{"Material": "RAW-1", "ProductionPlant": "PL01"}]
    target_rows = [{"PRDID": "PRD-1", "LOCID": "PL01"}]

    res = client.post("/api/recon/value-mapping/live-prepass", json=_body(source_rows, target_rows))
    assert res.status_code == 200, res.text
    product_by_value = {m["source_value"]: m for m in res.json()["product"]["matches"]}
    assert product_by_value["RAW-1"]["confidence"] == "none"
    assert product_by_value["RAW-1"]["rule"] == "value_pairing.unpaired"


def test_live_prepass_400s_on_missing_source_rows(client):
    res = client.post(
        "/api/recon/value-mapping/live-prepass",
        json=_body([], [{"PRDID": "MAT-1", "LOCID": "PL01"}]),
    )
    assert res.status_code == 400
    assert "source" in res.json()["detail"].lower()


def test_live_prepass_400s_on_missing_target_rows(client):
    res = client.post(
        "/api/recon/value-mapping/live-prepass",
        json=_body([{"Material": "MAT-1", "ProductionPlant": "PL01"}], []),
    )
    assert res.status_code == 400
    assert "target" in res.json()["detail"].lower()
