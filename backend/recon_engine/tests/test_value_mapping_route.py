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


def test_run_value_mapping_returns_a_mapping_per_key_pair(client):
    # No date column present in the rows below, so the default key_pairs'
    # date pair (RequestedDeliveryDate/PERIODID0_TSTAMP) is detected and
    # excluded, leaving exactly two pairable pairs in order: product, location.
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
    pairs = body["pairs"]
    assert len(pairs) == 2

    product = pairs[0]
    assert product["source_field"] == "Material"
    assert product["target_field"] == "PRDID"
    product_by_value = {m["source_value"]: m for m in product["matches"]}
    assert product_by_value["MAT-1"]["confidence"] == "very_high"
    assert product_by_value["MAT-1"]["rule"] == "value_pairing.identity"
    # No LLM configured and no identity/library hit -> genuinely unpaired,
    # never guessed and never silently dropped.
    assert product_by_value["RAW-1"]["confidence"] == "none"
    assert product_by_value["RAW-1"]["rule"] == "value_pairing.unpaired"

    location = pairs[1]
    assert location["source_field"] == "ProductionPlant"
    assert location["target_field"] == "LOCID"
    location_by_value = {m["source_value"]: m for m in location["matches"]}
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


def test_run_value_mapping_resolves_arbitrary_key_pairs(client):
    # An Excel upload's headers won't literally be "Material"/"PRDID" — the
    # wizard sends every confirmed key pair's actual column names as a
    # key_pairs JSON array, however many there are.
    source_rows = [{"SKU": "MAT-1", "Plant Code": "PL01"}]
    target_rows = [{"Product Code": "MAT-1", "Location ID": "PL01"}]

    key_pairs = [
        {"source_field": "SKU", "target_field": "Product Code"},
        {"source_field": "Plant Code", "target_field": "Location ID"},
    ]
    body = {
        **_rows_body(source_rows, target_rows),
        "key_pairs": json.dumps(key_pairs),
    }
    res = client.post("/api/recon/value-mapping/run", data=body)
    assert res.status_code == 200, res.text
    pairs = res.json()["pairs"]
    assert len(pairs) == 2

    assert pairs[0]["source_field"] == "SKU"
    assert pairs[0]["target_field"] == "Product Code"
    product_by_value = {m["source_value"]: m for m in pairs[0]["matches"]}
    assert product_by_value["MAT-1"]["confidence"] == "very_high"

    assert pairs[1]["source_field"] == "Plant Code"
    assert pairs[1]["target_field"] == "Location ID"
    location_by_value = {m["source_value"]: m for m in pairs[1]["matches"]}
    assert location_by_value["PL01"]["confidence"] == "very_high"


def test_run_value_mapping_supports_more_than_two_key_pairs(client):
    # A third key pair beyond product/location (e.g. a region/hierarchy
    # field) must be paired too, not silently dropped.
    source_rows = [{"SKU": "MAT-1", "Plant Code": "PL01", "Region": "APAC"}]
    target_rows = [{"Product Code": "MAT-1", "Location ID": "PL01", "RegionCode": "APAC"}]

    key_pairs = [
        {"source_field": "SKU", "target_field": "Product Code"},
        {"source_field": "Plant Code", "target_field": "Location ID"},
        {"source_field": "Region", "target_field": "RegionCode"},
    ]
    body = {
        **_rows_body(source_rows, target_rows),
        "key_pairs": json.dumps(key_pairs),
    }
    res = client.post("/api/recon/value-mapping/run", data=body)
    assert res.status_code == 200, res.text
    pairs = res.json()["pairs"]
    assert len(pairs) == 3
    assert pairs[2]["source_field"] == "Region"
    assert pairs[2]["target_field"] == "RegionCode"
    region_by_value = {m["source_value"]: m for m in pairs[2]["matches"]}
    assert region_by_value["APAC"]["confidence"] == "very_high"


def test_run_value_mapping_excludes_the_date_pair_from_pairs(client):
    # A key pair whose own VALUES look like dates is used only for
    # corroboration — it must never appear in the returned pairs.
    source_rows = [{"SKU": "MAT-1", "OrderDate": "2024-01-01"}]
    target_rows = [{"Product Code": "MAT-1", "PERIODID0_TSTAMP": "2024-01-01"}]

    key_pairs = [
        {"source_field": "SKU", "target_field": "Product Code"},
        {"source_field": "OrderDate", "target_field": "PERIODID0_TSTAMP"},
    ]
    body = {
        **_rows_body(source_rows, target_rows),
        "key_pairs": json.dumps(key_pairs),
    }
    res = client.post("/api/recon/value-mapping/run", data=body)
    assert res.status_code == 200, res.text
    pairs = res.json()["pairs"]
    assert len(pairs) == 1
    assert pairs[0]["source_field"] == "SKU"


def test_run_value_mapping_detects_the_date_pair_by_value_not_name(client):
    # Column named nothing date-like at all ("Col1"/"Col2") but whose actual
    # values are dates -> still recognized and excluded from pairing. Proves
    # detection is value-based, not a column-name guess.
    source_rows = [
        {"SKU": "MAT-1", "Col1": "2024-01-01"},
        {"SKU": "MAT-1", "Col1": "2024-02-01"},
    ]
    target_rows = [{"Product Code": "MAT-1", "Col2": "2024-01-01"}]

    key_pairs = [
        {"source_field": "SKU", "target_field": "Product Code"},
        {"source_field": "Col1", "target_field": "Col2"},
    ]
    body = {
        **_rows_body(source_rows, target_rows),
        "key_pairs": json.dumps(key_pairs),
    }
    res = client.post("/api/recon/value-mapping/run", data=body)
    assert res.status_code == 200, res.text
    pairs = res.json()["pairs"]
    assert len(pairs) == 1
    assert pairs[0]["source_field"] == "SKU"


def test_run_value_mapping_pairs_a_date_named_column_with_non_date_values(client):
    # Column NAMED like a date ("OrderDate"/"PERIODID0_TSTAMP") but whose
    # actual values are plain codes, not dates -> paired normally, not
    # excluded. Proves the name alone is never enough to skip a pair.
    source_rows = [{"SKU": "MAT-1", "OrderDate": "BATCH-9"}]
    target_rows = [{"Product Code": "MAT-1", "PERIODID0_TSTAMP": "BATCH-9"}]

    key_pairs = [
        {"source_field": "SKU", "target_field": "Product Code"},
        {"source_field": "OrderDate", "target_field": "PERIODID0_TSTAMP"},
    ]
    body = {
        **_rows_body(source_rows, target_rows),
        "key_pairs": json.dumps(key_pairs),
    }
    res = client.post("/api/recon/value-mapping/run", data=body)
    assert res.status_code == 200, res.text
    pairs = res.json()["pairs"]
    assert len(pairs) == 2
    assert pairs[1]["source_field"] == "OrderDate"
    batch_by_value = {m["source_value"]: m for m in pairs[1]["matches"]}
    assert batch_by_value["BATCH-9"]["confidence"] == "very_high"


def test_run_value_mapping_400s_on_missing_custom_key_column(client):
    source_rows = [{"Plant Code": "PL01"}]
    target_rows = [{"Product Code": "MAT-1", "Location ID": "PL01"}]

    key_pairs = [{"source_field": "SKU", "target_field": "Product Code"}]
    body = {
        **_rows_body(source_rows, target_rows),
        "key_pairs": json.dumps(key_pairs),
    }
    res = client.post("/api/recon/value-mapping/run", data=body)
    assert res.status_code == 400
    assert "SKU" in res.json()["detail"]


def test_run_value_mapping_400s_on_invalid_key_pairs_json(client):
    source_rows = [{"Material": "MAT-1"}]
    target_rows = [{"PRDID": "MAT-1"}]

    body = {
        **_rows_body(source_rows, target_rows),
        "key_pairs": "not json",
    }
    res = client.post("/api/recon/value-mapping/run", data=body)
    assert res.status_code == 400


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
    product_by_value = {m["source_value"]: m for m in res.json()["pairs"][0]["matches"]}
    assert product_by_value["MAT-1"]["confidence"] == "none"
    assert product_by_value["MAT-1"]["rule"] == "value_pairing.unpaired"
