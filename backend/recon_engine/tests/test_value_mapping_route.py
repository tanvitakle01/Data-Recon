"""Coverage for POST /api/recon/value-mapping/run — the thin HTTP wrapper the
Mapping Review page's "Run Deterministic Mapping" button calls. The pipeline
itself (recon_engine.value_pairing) is covered by test_value_pairing.py; this
only exercises the endpoint's request handling (rows-vs-file resolution,
column resolution, error paths). No LLM key is configured in these tests, so
every case here resolves via the identity pre-pass or ends up unpaired —
never an LLM call.
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
        {"Material": "MAT-1", "ProductionPlant": "PL01"},
        {"Material": "RAW-1", "ProductionPlant": "PL01"},
    ]
    target_rows = [
        {"PRDID": "MAT-1", "LOCID": "PL01"},
    ]

    res = client.post("/api/recon/value-mapping/run", data=_rows_body(source_rows, target_rows))
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["product"]["source_field"] == "Material"
    assert body["product"]["target_field"] == "PRDID"
    product_by_value = {m["source_value"]: m for m in body["product"]["matches"]}
    assert product_by_value["MAT-1"]["confidence"] == "very_high"
    assert product_by_value["MAT-1"]["rule"] == "value_pairing.identity"
    # No LLM configured and no identity/library hit -> genuinely unpaired,
    # never guessed and never silently dropped.
    assert product_by_value["RAW-1"]["confidence"] == "none"
    assert product_by_value["RAW-1"]["rule"] == "value_pairing.unpaired"

    assert body["location"]["source_field"] == "ProductionPlant"
    assert body["location"]["target_field"] == "LOCID"
    location_by_value = {m["source_value"]: m for m in body["location"]["matches"]}
    assert location_by_value["PL01"]["confidence"] == "very_high"


def test_run_value_mapping_is_case_insensitive_on_column_names(client):
    # Real SAP/IBP extracts don't always arrive with exactly-cased headers;
    # the endpoint resolves columns case-insensitively (mirrors
    # service._resolve_source_name), not the pipeline itself.
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


def test_run_value_mapping_resolves_custom_field_names(client):
    # An Excel upload's headers won't literally be "Material"/"PRDID" — the
    # wizard resolves the confirmed field mapping's actual column names and
    # sends them as source_product_field/target_product_field/etc.
    source_rows = [{"SKU": "MAT-1", "Plant Code": "PL01"}]
    target_rows = [{"Product Code": "MAT-1", "Location ID": "PL01"}]

    body = {
        **_rows_body(source_rows, target_rows),
        "source_product_field": "SKU",
        "target_product_field": "Product Code",
        "source_location_field": "Plant Code",
        "target_location_field": "Location ID",
    }
    res = client.post("/api/recon/value-mapping/run", data=body)
    assert res.status_code == 200, res.text
    payload = res.json()

    assert payload["product"]["source_field"] == "SKU"
    assert payload["product"]["target_field"] == "Product Code"
    product_by_value = {m["source_value"]: m for m in payload["product"]["matches"]}
    assert product_by_value["MAT-1"]["confidence"] == "very_high"

    assert payload["location"]["source_field"] == "Plant Code"
    assert payload["location"]["target_field"] == "Location ID"
    location_by_value = {m["source_value"]: m for m in payload["location"]["matches"]}
    assert location_by_value["PL01"]["confidence"] == "very_high"


def test_run_value_mapping_400s_on_missing_custom_product_column(client):
    source_rows = [{"Plant Code": "PL01"}]
    target_rows = [{"Product Code": "MAT-1", "Location ID": "PL01"}]

    body = {
        **_rows_body(source_rows, target_rows),
        "source_product_field": "SKU",
        "target_product_field": "Product Code",
    }
    res = client.post("/api/recon/value-mapping/run", data=body)
    assert res.status_code == 400
    assert "SKU" in res.json()["detail"]


def test_run_value_mapping_accepts_connector_and_mapping_sheet_context(client):
    # source_connector/target_connector/mapping_sheet are optional — the route
    # must not choke on them (they key the value-pair library + feed the LLM
    # prompt when pairing actually runs), and unpaired values still surface.
    source_rows = [{"Material": "MAT-1", "ProductionPlant": "PL01"}]
    target_rows = [{"PRDID": "PRD-1", "LOCID": "LOC-1"}]

    body = {
        **_rows_body(source_rows, target_rows),
        "source_connector": "s4",
        "target_connector": "ibp",
        "mapping_sheet": json.dumps({"rows": [{"note": "Material maps via a fixed prefix"}]}),
    }
    res = client.post("/api/recon/value-mapping/run", data=body)
    assert res.status_code == 200, res.text
    product_by_value = {m["source_value"]: m for m in res.json()["product"]["matches"]}
    assert product_by_value["MAT-1"]["confidence"] == "none"
    assert product_by_value["MAT-1"]["rule"] == "value_pairing.unpaired"
