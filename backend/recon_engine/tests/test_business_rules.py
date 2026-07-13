"""Coverage for the structured Business Rules Builder replacing free-text
`rules`: normalization, precedence over legacy text, and that every compiler
(stub and Groq) actually receives the structured data.
"""

from __future__ import annotations

import json

from backend.recon_engine import service
from backend.recon_engine.compiler.groq_compiler import GroqContractCompiler
from backend.recon_engine.compiler.stub_compiler import StubContractCompiler
from backend.recon_engine.models.rules import BusinessRules, normalize_business_rules

MAPPING_SHEET = [
    {"source_col": "id", "target_col": "id", "role": "key"},
    {"source_col": "qty", "target_col": "qty", "role": "compare"},
]


# ── normalize_business_rules ─────────────────────────────────────────────────

def test_normalize_trims_whitespace_and_drops_empty_rows_preserving_order():
    raw = {
        "transformation_rules": [
            {"field": "  Material  ", "instruction": "  Remove leading zeros  "},
            {"field": "", "instruction": "should be dropped: no field"},
            {"field": "Plant", "instruction": "   "},  # dropped: no instruction
            {"field": "Date", "instruction": "Normalize date"},
        ],
        "matching_rules": [{"field": "Plant", "instruction": "1000 = 1010"}],
        "filter_rules": [],
    }
    normalized = normalize_business_rules(raw)

    assert [r.model_dump() for r in normalized.transformation_rules] == [
        {"field": "Material", "instruction": "Remove leading zeros"},
        {"field": "Date", "instruction": "Normalize date"},
    ]
    assert [r.model_dump() for r in normalized.matching_rules] == [
        {"field": "Plant", "instruction": "1000 = 1010"}
    ]
    assert normalized.filter_rules == []


def test_normalize_business_rules_accepts_none():
    normalized = normalize_business_rules(None)
    assert normalized.is_empty()


def test_to_prompt_text_is_deterministic_and_grouped_by_category():
    rules = BusinessRules(
        transformation_rules=[{"field": "Material", "instruction": "Remove leading zeros"}],
        matching_rules=[{"field": "Plant", "instruction": "1000 = 1010"}],
        filter_rules=[{"field": "Quantity", "instruction": "Greater than 0"}],
    )
    text = rules.to_prompt_text()
    assert text.splitlines() == [
        "[Data Transformation] Material: Remove leading zeros",
        "[Matching] Plant: 1000 = 1010",
        "[Filter] Quantity: Greater than 0",
    ]


# ── stub compiler ────────────────────────────────────────────────────────────

def test_stub_compiler_compiles_transformation_rules_into_operations():
    """The stub now deterministically compiles the common transformation
    instructions into executable operations (not notes) so the offline path
    produces a correct shadow dataset. Rules it cannot parse still fall back to
    notes, but a recognised one like "Remove leading zeros" must become an op."""
    business_rules = BusinessRules(
        transformation_rules=[{"field": "id", "instruction": "Remove leading zeros"}],
    )
    draft = StubContractCompiler().compile(
        mapping_sheet=MAPPING_SHEET, rules="", business_rules=business_rules,
        source_schema=["id", "qty"], target_schema=["id", "qty"],
        comparison_type="sales_history", source_type="s4", target_type="ibp",
    )
    assert any(
        op.op == "remove_leading_zeros" and op.field == "id" for op in draft.operations
    ), draft.operations
    # The executable rule must NOT be parked in notes.
    assert "Remove leading zeros" not in (draft.notes or "")


def test_stub_compiler_preserves_uninterpretable_rules_in_notes():
    """A transformation rule the deterministic parser can't recognise is
    preserved verbatim in notes rather than silently dropped or guessed at."""
    business_rules = BusinessRules(
        transformation_rules=[{"field": "id", "instruction": "apply the usual finance logic"}],
    )
    draft = StubContractCompiler().compile(
        mapping_sheet=MAPPING_SHEET, rules="", business_rules=business_rules,
        source_schema=["id", "qty"], target_schema=["id", "qty"],
        comparison_type="sales_history", source_type="s4", target_type="ibp",
    )
    assert "apply the usual finance logic" in (draft.notes or "")


# ── Groq prompt plumbing ─────────────────────────────────────────────────────

def test_groq_prompt_carries_structured_business_rules():
    compiler = GroqContractCompiler(api_key="fake-key-for-prompt-assembly-only")
    business_rules = BusinessRules(
        transformation_rules=[{"field": "Material", "instruction": "Remove leading zeros"}],
        matching_rules=[{"field": "Plant", "instruction": "1000 = 1010"}],
        filter_rules=[{"field": "Quantity", "instruction": "Greater than 0"}],
    )
    messages = compiler._build_prompt(
        mapping_sheet=MAPPING_SHEET, rules="", business_rules=business_rules,
        source_schema=["id"], target_schema=["id"],
        comparison_type="x", source_type="s4", target_type="ibp",
    )
    user_payload = json.loads(messages[-1]["content"])
    assert user_payload["business_rules"] == {
        "transformation_rules": [{"field": "Material", "instruction": "Remove leading zeros"}],
        "matching_rules": [{"field": "Plant", "instruction": "1000 = 1010"}],
        "filter_rules": [{"field": "Quantity", "instruction": "Greater than 0"}],
    }


def test_groq_prompt_explains_structured_rules_take_priority():
    system_text = GroqContractCompiler(api_key="fake")._build_prompt(
        mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id"], target_schema=["id"],
        comparison_type="x", source_type="s4", target_type="ibp",
    )[0]["content"]
    assert "business_rules" in system_text
    assert "authoritative source" in system_text


# ── service.compile_draft precedence ─────────────────────────────────────────

def test_compile_draft_prefers_structured_rules_over_legacy_text(monkeypatch):
    """When business_rules is non-empty, the legacy free-text `rules` string
    must not reach the compiler at all (service.compile_draft's precedence
    rule) — the stub's notes should reflect only the structured rules."""
    captured: dict = {}

    class _RecordingCompiler(StubContractCompiler):
        def compile(self, **kwargs):
            captured.update(kwargs)
            return super().compile(**kwargs)

    business_rules = BusinessRules(
        transformation_rules=[{"field": "id", "instruction": "Remove leading zeros"}],
    )
    draft, _ = service.compile_draft(
        mapping_sheet=MAPPING_SHEET,
        rules="this legacy text should be ignored",
        business_rules=business_rules,
        source_schema=["id", "qty"], target_schema=["id", "qty"],
        comparison_type="sales_history", source_type="s4", target_type="ibp",
        compiler=_RecordingCompiler(),
    )
    assert captured["rules"] == ""
    assert captured["business_rules"].transformation_rules[0].instruction == "Remove leading zeros"
    assert "this legacy text should be ignored" not in (draft.notes or "")


def test_compile_draft_falls_back_to_legacy_rules_when_structured_empty(monkeypatch):
    captured: dict = {}

    class _RecordingCompiler(StubContractCompiler):
        def compile(self, **kwargs):
            captured.update(kwargs)
            return super().compile(**kwargs)

    draft, _ = service.compile_draft(
        mapping_sheet=MAPPING_SHEET,
        rules="quantities must match exactly",
        business_rules=None,
        source_schema=["id", "qty"], target_schema=["id", "qty"],
        comparison_type="sales_history", source_type="s4", target_type="ibp",
        compiler=_RecordingCompiler(),
    )
    assert captured["rules"] == "quantities must match exactly"
    assert captured["business_rules"].is_empty()
    assert draft.notes == "quantities must match exactly"
