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


# ── MDT Auxiliary Field Recommender surface + evidence-only boundary ─────────

def test_run_value_mapping_returns_auxiliary_field_report(client):
    source_rows = [{"Material": "MAT-1", "MaterialGroup": "FG", "ProductionPlant": "S101"}]
    target_rows = [
        {"PRDID": "P1", "PRODGROUP": "FG", "LOCID": "LOC-1", "LOCNAME": "Distribution S101 UK",
         "PRODDESC": "Widget", "PRDIDDEM": ""},
    ]
    res = client.post("/api/recon/value-mapping/run", data=_rows_body(source_rows, target_rows))
    assert res.status_code == 200, res.text
    aux = res.json()["auxiliary_fields"]
    assert set(aux) == {"target_product", "target_location", "source_product", "source_plant"}

    loc = {c["seed_name"]: c for c in aux["target_location"]}
    # LOCNAME exists + populated + consumed by location Rule 2.
    assert loc["LOCNAME"]["confirmed_existing"] and loc["LOCNAME"]["confirmed_populated"]
    assert loc["LOCNAME"]["consumed"] is True
    # A validation-only attribute is reported but tagged not-consumed.
    assert loc["LOCATIONTYPE"]["consumed"] is False

    prod = {c["seed_name"]: c for c in aux["target_product"]}
    # PRDIDDEM present but 0% filled → not recommended, with a real fill rate.
    assert prod["PRDIDDEM"]["confirmed_existing"] is True
    assert prod["PRDIDDEM"]["confirmed_populated"] is False
    assert prod["PRDIDDEM"]["fill_rate"] == 0.0


def test_auxiliary_fields_never_leak_into_the_mapping_output(client):
    # LOCNAME drives a Rule 2 embedded-code match, but it must NEVER become a
    # mapping field — only Material/PRDID and ProductionPlant/LOCID are fields;
    # LOCNAME/PRODDESC/etc. may appear ONLY inside evidence text.
    source_rows = [{"Material": "MAT-1", "MaterialGroup": "FG", "ProductionPlant": "S101"}]
    target_rows = [
        {"PRDID": "MAT-1", "PRODGROUP": "FG", "LOCID": "LOC-1", "LOCNAME": "DC S101 hub",
         "LOCATIONTYPE": "Plant", "PRODDESC": "Widget"},
    ]
    body = client.post("/api/recon/value-mapping/run", data=_rows_body(source_rows, target_rows)).json()

    assert body["product"]["source_field"] == "Material"
    assert body["product"]["target_field"] == "PRDID"
    assert body["location"]["source_field"] == "ProductionPlant"
    assert body["location"]["target_field"] == "LOCID"

    aux_names = {"LOCNAME", "LOCATIONTYPE", "PRODDESC", "PRODGROUP", "MaterialGroup"}
    for mapping_key in ("product", "location"):
        for m in body[mapping_key]["matches"]:
            # No auxiliary column name is ever a mapped value/field.
            assert m["source_value"] not in aux_names
            assert (m["target_value"] or "") not in aux_names
            # And the ValueMatch shape carries no aux columns as keys.
            assert not (aux_names & set(m.keys()))

    # The plant matched via the embedded code in LOCNAME (proving LOCNAME was
    # used as evidence) — but only as evidence text, never as a field.
    loc_match = next(m for m in body["location"]["matches"] if m["source_value"] == "S101")
    assert loc_match["rule"] == "location.rule2_embedded_code"
    assert loc_match["target_value"] == "LOC-1"
