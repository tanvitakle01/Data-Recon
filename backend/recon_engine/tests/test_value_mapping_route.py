"""Coverage for POST /api/recon/value-mapping/run — the thin HTTP wrapper the
Mapping Review page's "Run Deterministic Mapping" button calls. The matchers
themselves (recon_engine.matching) are already covered by test_product.py /
test_location.py / test_matching.py; this only exercises the endpoint's
request handling (rows-vs-file resolution, column resolution, error paths).
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes.value_mapping import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _rows_body(source_rows, target_rows):
    return {
        "source_rows": json.dumps(source_rows),
        "target_rows": json.dumps(target_rows),
    }


def test_run_value_mapping_returns_product_and_location_mappings(client):
    source_rows = [
        {"Material": "MAT-1", "MaterialGroup": "FG", "ProductionPlant": "PL01"},
        {"Material": "RAW-1", "MaterialGroup": "RM", "ProductionPlant": "PL01"},
    ]
    target_rows = [
        {"PRDID": "MAT-1", "PRODGROUP": "FG", "LOCID": "PL01"},
    ]

    res = client.post("/api/recon/value-mapping/run", data=_rows_body(source_rows, target_rows))
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["product"]["source_field"] == "Material"
    assert body["product"]["target_field"] == "PRDID"
    product_by_value = {m["source_value"]: m for m in body["product"]["matches"]}
    assert product_by_value["MAT-1"]["confidence"] == "very_high"
    assert product_by_value["RAW-1"]["confidence"] == "out_of_scope"

    assert body["location"]["source_field"] == "ProductionPlant"
    assert body["location"]["target_field"] == "LOCID"
    location_by_value = {m["source_value"]: m for m in body["location"]["matches"]}
    assert location_by_value["PL01"]["confidence"] == "very_high"


def test_run_value_mapping_is_case_insensitive_on_column_names(client):
    # Real SAP/IBP extracts don't always arrive with exactly-cased headers;
    # the endpoint resolves columns case-insensitively (mirrors
    # service._resolve_source_name), not the matchers themselves.
    source_rows = [{"material": "MAT-1", "productionplant": "PL01"}]
    target_rows = [{"prdid": "MAT-1", "locid": "PL01"}]

    res = client.post("/api/recon/value-mapping/run", data=_rows_body(source_rows, target_rows))
    assert res.status_code == 200, res.text


def test_run_value_mapping_400s_on_missing_material_column(client):
    source_rows = [{"ProductionPlant": "PL01"}]
    target_rows = [{"PRDID": "MAT-1", "LOCID": "PL01"}]

    res = client.post("/api/recon/value-mapping/run", data=_rows_body(source_rows, target_rows))
    assert res.status_code == 400
    assert "Material" in res.json()["detail"]


def test_run_value_mapping_400s_on_missing_target_data(client):
    res = client.post(
        "/api/recon/value-mapping/run",
        data={"source_rows": json.dumps([{"Material": "MAT-1", "ProductionPlant": "PL01"}])},
    )
    assert res.status_code == 400
    assert "target" in res.json()["detail"].lower()
