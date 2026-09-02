"""Regression coverage for POST /api/recon/contracts/compile accepting BOTH
mapping_sheet shapes: a legacy list[dict] of rows, and the full object the
mapping-sheet parser produces (sheet_name/headers/rows/mapping_candidates/...).

Guards against a 422 that occurred when CompileRequest.mapping_sheet was
typed as list[dict] only — a parsed-worksheet dict would fail FastAPI/Pydantic
request validation before the compiler ever ran.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recon_engine.compiler.groq_compiler import GroqContractCompiler
from backend.routes.contracts import router
from backend.routes.script_transformations import router as script_router

FULL_PARSED_PAYLOAD = {
    "filename": "mappingSheet.xlsx",
    "sheet_name": "Sheet1",
    "sheets": ["Sheet1"],
    "headers": ["Target Fields", "Source Table/Field", "Transformation"],
    "rows": [
        {
            "Target Fields": "Product ID",
            "Source Table/Field": "MATNR",
            "Transformation": "Remove leading zeros",
        }
    ],
    "row_count": 1,
    "detected_columns": {
        "source": ["Source Table/Field"],
        "target": ["Target Fields"],
        "technical": [],
        "description": [],
        "transformation": ["Transformation"],
        "join_condition": [],
        "filter": [],
    },
    "mapping_candidates": [
        {
            "row_index": 0,
            "source_field": "MATNR",
            "target_field": "Product ID",
            "technical_field": None,
            "description": None,
            "transformation": "Remove leading zeros",
            "join_condition": None,
            "filter": None,
        }
    ],
    "transformation_notes": [],
    "join_conditions": [],
    "filters": [],
    "metadata": {"header_row_index": 0, "preamble_rows": [], "empty_row_indices": [], "column_count": 3},
}

LEGACY_ROWS = [{"source_field": "MATNR", "target_field": "Product ID", "role": "key"}]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.include_router(script_router)
    return TestClient(app)


def _compile_body(mapping_sheet) -> dict:
    return {
        "mapping_sheet": mapping_sheet,
        "rules": "",
        "source_schema": ["MATNR"],
        "target_schema": ["Product ID"],
        "comparison_type": "custom",
        "source_type": "excel",
        "target_type": "excel",
    }


def test_compile_accepts_structured_business_rules(client):
    """The Business Rules Builder payload reaches the compiler: a transformation
    rule compiles into an executable operation (never notes), while matching /
    filter rules the deterministic stub doesn't interpret are preserved in notes
    for the LLM/human downstream."""
    body = _compile_body(LEGACY_ROWS)
    body["transformation_rules"] = [{"field": "MATNR", "instruction": "Remove leading zeros"}]
    body["matching_rules"] = [{"field": "Product ID", "instruction": "Ignore case"}]
    body["filter_rules"] = [{"field": "Quantity", "instruction": "Greater than 0"}]

    res = client.post("/api/recon/contracts/compile", json=body)
    assert res.status_code == 200, res.text
    draft = res.json()["draft"]
    operations = draft["operations"]
    notes = draft["notes"] or ""

    # Executable transformation rule -> operation, not notes.
    assert any(
        op["op"] == "remove_leading_zeros" and op["field"] == "MATNR" for op in operations
    ), operations
    assert "Remove leading zeros" not in notes
    # Matching/filter rules the stub can't compile are still surfaced in notes.
    assert "Ignore case" in notes
    assert "Greater than 0" in notes


def test_compile_still_accepts_legacy_free_text_rules_only(client):
    """Backward compatibility: a caller sending only the old `rules` string
    (no structured fields) must keep working exactly as before."""
    body = _compile_body(LEGACY_ROWS)
    body["rules"] = "quantities must match exactly"

    res = client.post("/api/recon/contracts/compile", json=body)
    assert res.status_code == 200, res.text
    assert res.json()["draft"]["notes"] == "quantities must match exactly"


def test_compile_accepts_legacy_row_list(client):
    # business_key is never inferred from mapping_sheet content (that row's
    # "role": "key" is context only) — it must be supplied explicitly, as the
    # Rules step's confirmed field mapping does. See
    # test_compile_field_mapping_wiring.py for that wiring's dedicated coverage.
    body = _compile_body(LEGACY_ROWS)
    body["business_key"] = [{"source_field": "MATNR", "target_field": "Product ID"}]
    res = client.post("/api/recon/contracts/compile", json=body)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["degraded"] is False
    draft = body["draft"]
    assert draft["business_key"] == [{"source_field": "MATNR", "target_field": "Product ID"}]


def test_compile_accepts_full_parsed_mapping_sheet_object(client):
    body = _compile_body(FULL_PARSED_PAYLOAD)
    body["business_key"] = [{"source_field": "MATNR", "target_field": "Product ID"}]
    res = client.post("/api/recon/contracts/compile", json=body)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["degraded"] is False
    draft = body["draft"]
    # The full parsed-sheet object still reaches the compiler intact (as
    # context) rather than being rejected or flattened; business_key itself
    # comes from the explicit field above, not from mapping_candidates.
    assert draft["business_key"] == [{"source_field": "MATNR", "target_field": "Product ID"}]


def test_compile_degrades_instead_of_422_when_groq_is_configured_but_fails(client, monkeypatch):
    """End-to-end regression for the live bug: a real AZURE_FOUNDRY_MODEL (e.g.
    from backend/recon_engine/.env) whose network call fails must NOT surface
    as a 422 through this route — it must degrade to the stub compiler and
    return 200."""
    from backend.recon_engine.config import reset_settings_cache
    from backend.recon_engine.compiler.base import ContractCompilerError
    from backend.recon_engine.compiler.groq_compiler import GroqContractCompiler as _Groq

    monkeypatch.setenv("AZURE_FOUNDRY_MODEL", "gm_fake_model_for_this_test")
    reset_settings_cache()
    try:

        def _boom(self, **kwargs):
            raise ContractCompilerError("Groq API call failed: Connection error.")

        monkeypatch.setattr(_Groq, "compile", _boom)

        res = client.post("/api/recon/contracts/compile", json=_compile_body(LEGACY_ROWS))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["degraded"] is True
        assert "Azure AI Foundry compile failed" in body["degraded_reason"]
        assert body["draft"]["compiler"] == "stub"
    finally:
        reset_settings_cache()


def test_compile_route_uses_groq_when_it_succeeds(client, monkeypatch):
    """End-to-end: a successful Groq compile must reach the client as
    compiler=='groq', not be silently replaced by the stub."""
    from backend.recon_engine.config import reset_settings_cache
    from backend.recon_engine.models.contract import DraftContract

    monkeypatch.setenv("AZURE_FOUNDRY_MODEL", "gm_fake_model_for_this_test")
    reset_settings_cache()
    try:
        fake_draft = DraftContract(
            comparison_type="custom", source_type="excel", target_type="excel",
            business_key=[{"source_field": "MATNR", "target_field": "Product ID"}],
            source_schema=["MATNR"], target_schema=["Product ID"], compiler="groq",
        )
        monkeypatch.setattr(GroqContractCompiler, "compile", lambda self, **kw: fake_draft)

        res = client.post("/api/recon/contracts/compile", json=_compile_body(LEGACY_ROWS))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["degraded"] is False
        assert body["draft"]["compiler"] == "groq"
    finally:
        reset_settings_cache()


def test_compile_route_strict_mode_surfaces_groq_failure_instead_of_stub(client, monkeypatch):
    """RECON_GROQ_STRICT=true must not let a Groq failure quietly become a
    200-with-stub response — the caller needs to see it failed."""
    from backend.recon_engine.config import reset_settings_cache
    from backend.recon_engine.compiler.base import ContractCompilerError as _Err
    from backend.recon_engine.compiler.groq_compiler import GroqContractCompiler as _Groq

    monkeypatch.setenv("AZURE_FOUNDRY_MODEL", "gm_fake_model_for_this_test")
    monkeypatch.setenv("RECON_GROQ_STRICT", "true")
    reset_settings_cache()
    try:

        def _boom(self, **kwargs):
            raise _Err("Groq API call failed: Connection error.")

        monkeypatch.setattr(_Groq, "compile", _boom)

        res = client.post("/api/recon/contracts/compile", json=_compile_body(LEGACY_ROWS))
        assert res.status_code == 422
        assert "Connection error" in res.json()["detail"]
    finally:
        reset_settings_cache()


def test_compile_still_rejects_genuinely_invalid_requests(client):
    body = _compile_body(FULL_PARSED_PAYLOAD)
    del body["source_schema"]
    res = client.post("/api/recon/contracts/compile", json=body)
    assert res.status_code == 422


def test_compile_rejects_non_dict_non_list_mapping_sheet(client):
    res = client.post("/api/recon/contracts/compile", json=_compile_body("not-a-mapping-sheet"))
    assert res.status_code == 422


def test_compile_rejects_unwrapped_parsed_sheet_posted_as_the_whole_body(client):
    """The wrong-shape request: posting the parsed mapping-sheet object
    directly as the top-level body (e.g. a Swagger/manual-test mistake, or a
    caller that forgot to nest it under "mapping_sheet") instead of wrapping
    it inside CompileRequest. FastAPI must reject this with a 422 pinpointing
    the missing sibling fields — this is a genuinely different situation from
    the correctly-wrapped full-object case covered by
    test_compile_accepts_full_parsed_mapping_sheet_object above."""
    res = client.post("/api/recon/contracts/compile", json=FULL_PARSED_PAYLOAD)
    assert res.status_code == 422
    errors = res.json()["detail"]
    missing_fields = {tuple(e["loc"]) for e in errors if e["type"] == "missing"}
    assert ("body", "source_schema") in missing_fields
    assert ("body", "target_schema") in missing_fields
    assert ("body", "comparison_type") in missing_fields
    assert ("body", "source_type") in missing_fields
    assert ("body", "target_type") in missing_fields


def test_compile_accepts_correctly_wrapped_payload_matching_frontend_shape(client):
    """The correct shape the frontend actually sends
    (frontend/src/reconciliation/steps/TransformationSpecStep.jsx,
    generateContract): mapping_sheet nested as one field alongside its
    siblings, mirroring the exact payload built by buildMappingSheetPayload +
    the wizard state fallbacks (`?? ""`, `?? "excel"`, `?? "custom"`)."""
    payload = {
        "mapping_sheet": FULL_PARSED_PAYLOAD,
        "rules": "",
        "business_key": [{"source_field": "MATNR", "target_field": "Product ID"}],
        "source_schema": ["MATNR"],
        "target_schema": ["Product ID"],
        "comparison_type": "custom",
        "source_type": "excel",
        "target_type": "excel",
        "actor": "wizard-user",
    }
    res = client.post("/api/recon/contracts/compile", json=payload)
    assert res.status_code == 200, res.text
    assert res.json()["draft"]["business_key"] == [
        {"source_field": "MATNR", "target_field": "Product ID"}
    ]


def test_groq_prompt_carries_full_parsed_object_unstripped():
    """The parsed object must reach the Groq user message byte-for-byte —
    the compiler must not flatten, summarise, or drop any of its keys."""
    compiler = GroqContractCompiler(api_key="fake-key-for-prompt-assembly-only")
    messages = compiler._build_prompt(
        mapping_sheet=FULL_PARSED_PAYLOAD,
        rules="quantities must match",
        source_schema=["MATNR"],
        target_schema=["Product ID"],
        comparison_type="custom",
        source_type="excel",
        target_type="ibp",
    )
    user_payload = json.loads(messages[-1]["content"])
    assert user_payload["mapping_sheet"] == FULL_PARSED_PAYLOAD


def test_groq_prompt_carries_legacy_row_list_unstripped():
    compiler = GroqContractCompiler(api_key="fake-key-for-prompt-assembly-only")
    messages = compiler._build_prompt(
        mapping_sheet=LEGACY_ROWS,
        rules="",
        source_schema=["MATNR"],
        target_schema=["Product ID"],
        comparison_type="custom",
        source_type="excel",
        target_type="ibp",
    )
    user_payload = json.loads(messages[-1]["content"])
    assert user_payload["mapping_sheet"] == LEGACY_ROWS


# ── the same DTO shape on the script-transformation generator endpoint ───────

def _generate_body(mapping_sheet) -> dict:
    return {
        "mapping_sheet": mapping_sheet,
        "rules": "",
        "source_schema": ["MATNR"],
        "target_schema": ["Product ID"],
    }


def test_generate_accepts_legacy_row_list(client):
    res = client.post("/api/recon/transformations/generate", json=_generate_body(LEGACY_ROWS))
    assert res.status_code == 200, res.text


def test_generate_accepts_full_parsed_mapping_sheet_object(client):
    res = client.post(
        "/api/recon/transformations/generate", json=_generate_body(FULL_PARSED_PAYLOAD)
    )
    assert res.status_code == 200, res.text
    script = res.json()["script"]
    assert any("matnr" in step.lower() for step in script["explanation"])
