"""Coverage for the business_key/compare_fields/value_mappings wiring added to
service.compile_draft and CompileRequest.

Neither Groq nor the stub compiler is ever allowed to decide business_key,
compare_fields, or value_mappings (see ContractBody's docstring and the
Groq system preamble) — they must be attached onto the draft afterward, from
the caller's confirmed field mapping and (once approved) the deterministic
matching engine's output. This was previously documented but never
implemented; these tests pin the fix.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recon_engine import service
from backend.recon_engine.compiler.stub_compiler import StubContractCompiler
from backend.routes.contracts import router

MAPPING_SHEET = [{"source_field": "MATNR", "target_field": "PRDID", "role": "key"}]

SAMPLE_VALUE_MAPPING = {
    "source_field": "MATNR",
    "target_field": "PRDID",
    "matches": [
        {
            "source_value": "MAT-1",
            "target_value": "MAT-1",
            "confidence": "very_high",
            "rule": "product.rule1_exact_id_group_aligned",
            "evidence": "Exact match.",
            "row_count": 3,
        }
    ],
}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_compile_draft_attaches_confirmed_field_mapping_and_value_mappings():
    draft, _ = service.compile_draft(
        mapping_sheet=MAPPING_SHEET,
        rules="",
        aggregation_rules=None,
        business_key=[{"source_field": "matnr", "target_field": "PRDID"}],  # lowercase on purpose
        compare_fields=[{"source_field": "QTY", "target_field": "SALESORDERREQUEST"}],
        value_mappings=[SAMPLE_VALUE_MAPPING],
        source_schema=["MATNR", "QTY"],
        target_schema=["PRDID", "SALESORDERREQUEST"],
        comparison_type="custom",
        source_type="excel",
        target_type="excel",
        compiler=StubContractCompiler(),
    )

    assert len(draft.business_key) == 1
    # Resolved case-insensitively against the real source schema, like
    # aggregation_rules' _resolve_source_name.
    assert draft.business_key[0].source_field == "MATNR"
    assert draft.business_key[0].target_field == "PRDID"

    assert len(draft.compare_fields) == 1
    assert draft.compare_fields[0].source_field == "QTY"

    assert len(draft.value_mappings) == 1
    assert draft.value_mappings[0].source_field == "MATNR"
    assert draft.value_mappings[0].matches[0].source_value == "MAT-1"


def test_compile_draft_drops_malformed_value_mapping_without_raising():
    draft, _ = service.compile_draft(
        mapping_sheet=MAPPING_SHEET,
        rules="",
        value_mappings=[{"not": "a value mapping"}],
        source_schema=["MATNR"],
        target_schema=["PRDID"],
        comparison_type="custom",
        source_type="excel",
        target_type="excel",
        compiler=StubContractCompiler(),
    )
    assert draft.value_mappings == []


def test_compile_draft_leaves_fields_empty_when_nothing_supplied():
    draft, _ = service.compile_draft(
        mapping_sheet=MAPPING_SHEET,
        rules="",
        source_schema=["MATNR"],
        target_schema=["PRDID"],
        comparison_type="custom",
        source_type="excel",
        target_type="excel",
        compiler=StubContractCompiler(),
    )
    assert draft.business_key == []
    assert draft.compare_fields == []
    assert draft.value_mappings == []


def test_compile_route_attaches_business_key_and_value_mappings_onto_the_draft(client):
    body = {
        "mapping_sheet": MAPPING_SHEET,
        "rules": "",
        "business_key": [{"source_field": "MATNR", "target_field": "PRDID"}],
        "compare_fields": [],
        "value_mappings": [SAMPLE_VALUE_MAPPING],
        "source_schema": ["MATNR"],
        "target_schema": ["PRDID"],
        "comparison_type": "custom",
        "source_type": "excel",
        "target_type": "excel",
    }
    res = client.post("/api/recon/contracts/compile", json=body)
    assert res.status_code == 200, res.text
    draft = res.json()["draft"]
    assert draft["business_key"] == [{"source_field": "MATNR", "target_field": "PRDID"}]
    assert len(draft["value_mappings"]) == 1
    assert draft["value_mappings"][0]["source_field"] == "MATNR"
