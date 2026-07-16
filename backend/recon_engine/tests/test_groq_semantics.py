"""Coverage for the Groq compile path itself: that it actually runs, that a
failure is never silently swallowed, and that its output is schema-valid.

Two kinds of test live here:

* Mocked (always run, no network): exercise ``service.compile_draft``'s
  compiler-selection/strict-mode logic and the prompt/schema plumbing without
  ever calling the real API.
* Live (skipped unless a real ``GROQ_API_KEY`` is available in
  ``backend/.env``): prove the actual model, given the reported bug's mapping
  data, produces a contract that passes Gate 1 — the real regression this
  investigation was about. These read the key directly from the .env file so
  they aren't affected by ``conftest.isolated_store`` deliberately clearing
  ``GROQ_API_KEY`` from the environment for the offline tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.recon_engine import service
from backend.recon_engine.compiler.base import ContractCompilerError
from backend.recon_engine.compiler.groq_compiler import GroqContractCompiler
from backend.recon_engine.models.contract import ContractBody, DraftContract

MAPPING_SHEET = [
    {"source_col": "id", "target_col": "id", "role": "key"},
    {"source_col": "qty", "target_col": "qty", "role": "compare"},
]


def _read_live_groq_key() -> str | None:
    env_path = Path(__file__).resolve().parents[3] / "backend" / ".env"
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line.startswith("GROQ_API_KEY"):
            continue
        _, _, value = line.partition("=")
        return value.strip().strip("'\"") or None
    return None


_LIVE_GROQ_KEY = _read_live_groq_key()
requires_live_groq = pytest.mark.skipif(
    not _LIVE_GROQ_KEY, reason="No real GROQ_API_KEY in backend/.env for a live Groq call."
)


# ── mocked: compiler selection / strict mode ────────────────────────────────

def test_groq_path_marks_compiler_groq(monkeypatch):
    """A successful Groq compile must be reported as compiler=='groq', not stub."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake_key_for_this_test")
    from backend.recon_engine.config import reset_settings_cache

    reset_settings_cache()
    try:
        fake_draft = DraftContract(
            comparison_type="sales_history", source_type="s4", target_type="ibp",
            business_key=[{"source_field": "id", "target_field": "id"}],
            source_schema=["id", "qty"], target_schema=["id", "qty"],
            compiler="groq",
        )
        monkeypatch.setattr(GroqContractCompiler, "compile", lambda self, **kw: fake_draft)

        draft, degraded_reason = service.compile_draft(
            mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id", "qty"],
            target_schema=["id", "qty"], comparison_type="sales_history",
            source_type="s4", target_type="ibp",
        )
        assert draft.compiler == "groq"
        assert degraded_reason is None
    finally:
        reset_settings_cache()


def test_strict_mode_raises_instead_of_silently_falling_back_to_stub(monkeypatch):
    """RECON_GROQ_STRICT=true must surface a Groq failure, not mask it as stub."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake_key_for_this_test")
    monkeypatch.setenv("RECON_GROQ_STRICT", "true")
    from backend.recon_engine.config import reset_settings_cache

    reset_settings_cache()
    try:

        def _boom(self, **kwargs):
            raise ContractCompilerError("Groq API call failed: Connection error.")

        monkeypatch.setattr(GroqContractCompiler, "compile", _boom)

        with pytest.raises(ContractCompilerError, match="Connection error"):
            service.compile_draft(
                mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id", "qty"],
                target_schema=["id", "qty"], comparison_type="sales_history",
                source_type="s4", target_type="ibp",
            )
    finally:
        reset_settings_cache()


def test_non_strict_mode_still_degrades_to_stub(monkeypatch):
    """Default behaviour (RECON_GROQ_STRICT unset) is unchanged: degrade, don't raise."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake_key_for_this_test")
    from backend.recon_engine.config import reset_settings_cache

    reset_settings_cache()
    try:

        def _boom(self, **kwargs):
            raise ContractCompilerError("Groq API call failed: Connection error.")

        monkeypatch.setattr(GroqContractCompiler, "compile", _boom)

        draft, degraded_reason = service.compile_draft(
            mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id", "qty"],
            target_schema=["id", "qty"], comparison_type="sales_history",
            source_type="s4", target_type="ibp",
        )
        assert draft.compiler == "stub"
        assert degraded_reason is not None
    finally:
        reset_settings_cache()


# ── mocked: prompt/schema plumbing ──────────────────────────────────────────

def test_prompt_output_schema_excludes_server_owned_provenance_fields():
    """Regression: the model must never be asked for created_at/created_by/
    compiler/approval_status — those are server-assigned. Sending it the full
    DraftContract schema previously caused the model to emit "created_at":
    null, which failed validation before Gate 1 ever ran."""
    compiler = GroqContractCompiler(api_key="fake-key-for-prompt-assembly-only")
    messages = compiler._build_prompt(
        mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id"],
        target_schema=["id"], comparison_type="x", source_type="s4", target_type="ibp",
    )
    import json

    user_payload = json.loads(messages[-1]["content"])
    schema_props = set(user_payload["required_output_schema"]["properties"])
    assert schema_props == set(ContractBody.model_fields)
    assert "created_at" not in schema_props
    assert "compiler" not in schema_props
    assert "approval_status" not in schema_props


def test_prompt_instructs_schema_valid_field_names():
    compiler = GroqContractCompiler(api_key="fake-key-for-prompt-assembly-only")
    messages = compiler._build_prompt(
        mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id"],
        target_schema=["id"], comparison_type="x", source_type="s4", target_type="ibp",
    )
    system_text = messages[0]["content"]
    assert "technical_field" in system_text
    assert "NEVER emit a human-readable label" in system_text


def test_groq_compile_forces_provenance_regardless_of_model_output():
    """Even if the model's JSON omits/mis-sets provenance fields, the caller
    (not the model) decides created_at/created_by/compiler/approval_status."""
    compiler = GroqContractCompiler(api_key="fake-key-for-prompt-assembly-only")
    monkeypatch_payload = {
        "comparison_type": "sales_history", "source_type": "s4", "target_type": "ibp",
        "business_key": [{"source_field": "id", "target_field": "id"}],
        "source_schema": ["id"], "target_schema": ["id"],
    }
    compiler._llm.complete_json = lambda messages: monkeypatch_payload  # type: ignore[assignment]
    draft = compiler.compile(
        mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id"],
        target_schema=["id"], comparison_type="sales_history", source_type="s4", target_type="ibp",
    )
    assert draft.compiler == "groq"
    assert draft.created_at is not None


# ── live: proves the reported bug's mapping data now compiles cleanly ──────

_REPORTED_MAPPING_SHEET = {
    "mapping_candidates": [
        {"source_field": "VBAP-MATNR", "target_field": "Product ID", "technical_field": "PRDID"},
        {"source_field": "VBAP-WERKS", "target_field": "Location ID", "technical_field": "LOCID"},
        {"source_field": "VBAK-KUNNR", "target_field": "Customer ID", "technical_field": "CUSTID"},
        {"source_field": "VBAP-ERDAT", "target_field": "Order Entry CRSD", "technical_field": "ZSALESHISTORYCRSD"},
        {
            "source_field": "VBAP-EDATU",
            "target_field": "Requested Delivery Date",
            "technical_field": "KEYFIGUREDATE",
        },
    ]
}
_REPORTED_SOURCE_SCHEMA = ["Material", "Plnt", "Req.Dlv.Dt", "ReqDlvQty"]
_REPORTED_TARGET_SCHEMA = ["I_LOCID", "I_PRDID", "I_SALESORDERREQUEST", "KEYFIGUREDATE"]


@requires_live_groq
def test_live_groq_never_sets_business_key_or_compare_fields():
    """Regression for the NON-NEGOTIABLE SCOPE LIMIT in the system prompt: even
    given a mapping sheet whose rows look like key/compare candidates, the
    real model must obey the prompt and always emit business_key/
    compare_fields empty — those are attached afterward by
    service.compile_draft from the human's confirmed field mapping (the Rules
    step), never inferred by the model. (Previously this test expected the
    model to derive business_key itself and checked it against Gate 1; that
    responsibility moved to service.compile_draft — see
    test_compile_field_mapping_wiring.py for that wiring's coverage.)"""
    compiler = GroqContractCompiler(api_key=_LIVE_GROQ_KEY)
    draft = compiler.compile(
        mapping_sheet=_REPORTED_MAPPING_SHEET, rules="",
        source_schema=_REPORTED_SOURCE_SCHEMA, target_schema=_REPORTED_TARGET_SCHEMA,
        comparison_type="sales_history", source_type="s4", target_type="ibp",
    )
    assert draft.compiler == "groq"
    assert draft.business_key == []
    assert draft.compare_fields == []


@requires_live_groq
def test_live_groq_extracts_leading_zero_transformation():
    mapping_sheet = {
        "mapping_candidates": [
            {
                "source_field": "MATNR",
                "target_field": "PRDID",
                "technical_field": "PRDID",
                "transformation": "Remove leading zeros",
            },
        ]
    }
    compiler = GroqContractCompiler(api_key=_LIVE_GROQ_KEY)
    draft = compiler.compile(
        mapping_sheet=mapping_sheet, rules="", source_schema=["MATNR"], target_schema=["PRDID"],
        comparison_type="custom", source_type="excel", target_type="excel",
    )
    # "Remove leading zeros" now has a dedicated, purpose-built operation; the
    # LLM should emit it rather than the old numeric_cast approximation. Accept
    # either so the test isn't brittle to model phrasing, but the exact op is
    # the expected/preferred outcome.
    assert any(
        op.op in {"remove_leading_zeros", "numeric_cast"} and op.field == "MATNR"
        for op in draft.operations
    ), draft.operations


@requires_live_groq
def test_live_groq_extracts_join_and_filter_context():
    mapping_sheet = {
        "mapping_candidates": [
            {"source_field": "VBELN", "target_field": "ORDERID", "technical_field": "ORDERID"},
        ],
        "join_conditions": [{"text": "VBAP-VBELN = VBAK-VBELN"}],
        "filters": [{"text": "VBAK-VKORG = 5875"}],
    }
    compiler = GroqContractCompiler(api_key=_LIVE_GROQ_KEY)
    draft = compiler.compile(
        mapping_sheet=mapping_sheet, rules="", source_schema=["VBELN", "VKORG"],
        target_schema=["ORDERID"], comparison_type="custom", source_type="excel", target_type="excel",
    )
    include_filter = any(
        op.op == "include_value" and op.field == "VKORG" and "5875" in [str(v) for v in op.params.get("values", [])]
        for op in draft.operations
    )
    mentioned_in_notes = bool(draft.notes) and "5875" in draft.notes
    assert include_filter or mentioned_in_notes, draft.model_dump()

    join_mentioned = bool(draft.notes) and "VBAP-VBELN" in draft.notes and "VBAK-VBELN" in draft.notes
    assert join_mentioned, "join condition should be preserved in notes since it has no allow-listed operation"
