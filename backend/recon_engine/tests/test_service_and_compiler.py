from __future__ import annotations

import pandas as pd
import pytest

from backend.recon_engine import service
from backend.recon_engine.compiler import (
    ContractCompilerError,
    GroqContractCompiler,
    StubContractCompiler,
)
from backend.recon_engine.models.snapshot import RawLayer
from backend.recon_engine.models.value_mapping import Confidence, ValueMapping, ValueMatch

MAPPING_SHEET = [
    {"source_col": "id", "target_col": "id", "role": "key"},
    {"source_col": "qty", "target_col": "qty", "role": "compare"},
]


def _draft():
    draft, _degraded_reason = service.compile_draft(
        mapping_sheet=MAPPING_SHEET,
        rules="quantities must match exactly",
        # business_key/compare_fields are the Rules step's confirmed field
        # mapping — never inferred by a compiler from mapping_sheet (see
        # ContractBody's docstring) — so tests exercising the full lifecycle
        # supply them explicitly, exactly as the wizard's generateContract()
        # now does.
        business_key=[{"source_field": "id", "target_field": "id"}],
        compare_fields=[{"source_field": "qty", "target_field": "qty"}],
        source_schema=["id", "qty"],
        target_schema=["id", "qty"],
        comparison_type="sales_history",
        source_type="s4",
        target_type="ibp",
    )
    return draft


# ── compiler scaffolding ────────────────────────────────────────────────────

def test_groq_compiler_is_scaffolding_only():
    compiler = GroqContractCompiler()
    assert compiler.is_configured is False  # no AZURE_FOUNDRY_MODEL in tests
    with pytest.raises(ContractCompilerError):
        compiler.compile(
            mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id"],
            target_schema=["id"], comparison_type="x", source_type="s4", target_type="ibp",
        )


def test_stub_compiler_builds_valid_draft():
    draft = StubContractCompiler().compile(
        mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id", "qty"],
        target_schema=["id", "qty"], comparison_type="sales_history",
        source_type="s4", target_type="ibp",
    )
    assert draft.compiler == "stub"
    # business_key/compare_fields are never inferred by the compiler from
    # mapping_sheet's "role" hints (that responsibility moved to
    # service.compile_draft's explicit business_key/compare_fields params —
    # see the _draft() helper above and test_compile_field_mapping_wiring.py).
    assert draft.business_key == []
    assert draft.compare_fields == []


def test_stub_compiler_resolves_technical_field_for_transformation_ops():
    """Regression: real mapping_sheet_parser output never sets "role" (field
    mapping is not this compiler's job), and carries a human-readable
    target_field ("Product ID") plus a technical_field ("I_PRDID") that isn't
    in the source schema at all — only "source_field" is. The stub must still
    resolve a row to its schema-valid SOURCE field to compile transformation
    text into operations, and must skip (not fabricate) an unresolvable row."""
    mapping_sheet = {
        "mapping_candidates": [
            {
                "source_field": "Material", "target_field": "Product ID",
                "technical_field": "I_PRDID", "transformation": "Remove leading zeros",
            },
            {"source_field": "Nonexistent", "target_field": "Also Nonexistent", "technical_field": None},
        ]
    }
    source_schema = ["Material", "ReqDlvQty"]
    target_schema = ["I_PRDID", "I_SALESORDERREQUEST"]

    draft = StubContractCompiler().compile(
        mapping_sheet=mapping_sheet, rules="", source_schema=source_schema,
        target_schema=target_schema, comparison_type="sales_history",
        source_type="s4", target_type="ibp",
    )

    assert draft.business_key == []
    assert draft.compare_fields == []
    assert any(
        op.op == "remove_leading_zeros" and op.field == "Material" for op in draft.operations
    ), draft.operations
    assert "Nonexistent" in (draft.notes or "")  # skipped row is surfaced, not silently dropped


def test_compile_draft_never_fails_when_groq_is_configured_but_unreachable(monkeypatch):
    """Regression: a live AZURE_FOUNDRY_MODEL (e.g. from
    backend/recon_engine/.env) whose network call fails must degrade to the
    stub compiler, not surface a 422 to the caller — mirrors the
    script-transformation generator's fallback."""
    monkeypatch.setenv("AZURE_FOUNDRY_MODEL", "gm_fake_model_for_this_test")
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
        assert "Azure AI Foundry compile failed" in degraded_reason
    finally:
        reset_settings_cache()


def test_compile_draft_no_degradation_when_groq_unconfigured():
    draft, degraded_reason = service.compile_draft(
        mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id", "qty"],
        target_schema=["id", "qty"], comparison_type="sales_history",
        source_type="s4", target_type="ibp",
    )
    assert draft.compiler == "stub"
    assert degraded_reason is None


def test_compile_draft_explicit_compiler_override_bypasses_auto_fallback():
    draft, degraded_reason = service.compile_draft(
        mapping_sheet=MAPPING_SHEET, rules="", source_schema=["id", "qty"],
        target_schema=["id", "qty"], comparison_type="sales_history",
        source_type="s4", target_type="ibp", compiler=StubContractCompiler(),
    )
    assert draft.compiler == "stub"
    assert degraded_reason is None


def test_stub_compiles_mapping_sheet_transformation_text_into_ops():
    """A mapping sheet's own transformation text becomes executable operations,
    not notes — the objective's Plant/Material example, offline."""
    mapping_sheet = [
        {"source_col": "Plant", "target_col": "LOCID", "role": "key",
         "transformation": "Add prefix PL; Append @S21400"},
        {"source_col": "Material", "target_col": "PRDID", "role": "key",
         "transformation": "Replace N01 with T01"},
    ]
    draft = StubContractCompiler().compile(
        mapping_sheet=mapping_sheet, rules="",
        source_schema=["Plant", "Material"], target_schema=["LOCID", "PRDID"],
        comparison_type="custom", source_type="excel", target_type="excel",
    )
    op_pairs = [(o.op, o.field) for o in draft.operations]
    assert ("prepend_prefix", "Plant") in op_pairs
    assert ("append_suffix", "Plant") in op_pairs
    assert ("replace_value", "Material") in op_pairs
    # prefix must run before suffix (execution order preserved).
    assert op_pairs.index(("prepend_prefix", "Plant")) < op_pairs.index(("append_suffix", "Plant"))
    assert "Add prefix PL" not in (draft.notes or "")


def test_full_pipeline_with_value_transformations_reconciles():
    """End-to-end proof of the redesign: Mapping Sheet + Rules -> Contract ->
    Operations -> Shadow Source -> reconcile against Target. The source Plant
    '5006' and Material 'N01-FG01' must be transformed to align with the target
    keys 'PL5006@S21400' / 'T01-FG01' and match."""
    source_df = pd.DataFrame({"Plant": ["5006"], "Material": ["N01-FG01"], "Qty": [10]})
    target_df = pd.DataFrame({"LOCID": ["PL5006@S21400"], "PRDID": ["T01-FG01"], "QTY": [10]})

    src_snap = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt_snap = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")

    mapping_sheet = [
        {"source_col": "Plant", "target_col": "LOCID", "role": "key",
         "transformation": "Add prefix PL; Append @S21400"},
        {"source_col": "Material", "target_col": "PRDID", "role": "key",
         "transformation": "Replace N01 with T01"},
        {"source_col": "Qty", "target_col": "QTY", "role": "compare"},
    ]
    src_cols = ["Plant", "Material", "Qty"]
    tgt_cols = ["LOCID", "PRDID", "QTY"]

    # Force the deterministic stub so the test never depends on a live LLM.
    draft, _ = service.compile_draft(
        mapping_sheet=mapping_sheet, rules="",
        business_key=[
            {"source_field": "Plant", "target_field": "LOCID"},
            {"source_field": "Material", "target_field": "PRDID"},
        ],
        compare_fields=[{"source_field": "Qty", "target_field": "QTY"}],
        source_schema=src_cols, target_schema=tgt_cols,
        comparison_type="custom", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )

    report = service.validate_draft(
        draft, source_columns=src_cols, target_columns=tgt_cols,
        source_sample=source_df, target_sample=target_df,
    )
    assert report["ok"], report

    contract = service.approve_contract(draft, approved_by="alice")
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
    )
    # The transformed shadow keys align with the target -> exact match.
    assert out["summary"]["match"] == 1, out["summary"]
    assert out["summary"].get("mismatch", 0) == 0


def test_run_reconciliation_excludes_unmapped_material_and_plant():
    """End-to-end: only VERY_HIGH/HIGH Material+Plant rows reach the join;
    MEDIUM/NONE rows are excluded entirely and counted separately, never as
    a mismatch. Also proves the excluded counts are deterministic
    across repeated runs of the same approved contract + snapshots."""
    source_df = pd.DataFrame({
        "Material": ["MAT-A", "MAT-B", "MAT-A"],
        "ProductionPlant": ["PL01", "PL01", "PL99"],
        "Qty": [10, 20, 30],
    })
    target_df = pd.DataFrame({"PRDID": ["MAT-A"], "LOCID": ["PL01"], "QTY": [10]})

    src_snap = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="s4")
    tgt_snap = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="ibp")

    product_vm = ValueMapping(
        source_field="Material",
        target_field="PRDID",
        matches=[
            ValueMatch(
                source_value="MAT-A", target_value="MAT-A",
                confidence=Confidence.VERY_HIGH, rule="t", evidence="e",
            ),
            ValueMatch(
                source_value="MAT-B", target_value=None,
                confidence=Confidence.MEDIUM, rule="t", evidence="e",
            ),
        ],
    )
    location_vm = ValueMapping(
        source_field="ProductionPlant",
        target_field="LOCID",
        matches=[
            ValueMatch(
                source_value="PL01", target_value="PL01",
                confidence=Confidence.VERY_HIGH, rule="t", evidence="e",
            ),
            ValueMatch(
                source_value="PL99", target_value=None,
                confidence=Confidence.NONE, rule="t", evidence="e",
            ),
        ],
    )

    draft, _ = service.compile_draft(
        mapping_sheet=[
            {"source_col": "Material", "target_col": "PRDID", "role": "key"},
            {"source_col": "ProductionPlant", "target_col": "LOCID", "role": "key"},
            {"source_col": "Qty", "target_col": "QTY", "role": "compare"},
        ],
        rules="",
        business_key=[
            {"source_field": "Material", "target_field": "PRDID"},
            {"source_field": "ProductionPlant", "target_field": "LOCID"},
        ],
        compare_fields=[{"source_field": "Qty", "target_field": "QTY"}],
        value_mappings=[product_vm.model_dump(), location_vm.model_dump()],
        source_schema=["Material", "ProductionPlant", "Qty"],
        target_schema=["PRDID", "LOCID", "QTY"],
        comparison_type="custom", source_type="s4", target_type="ibp",
        compiler=StubContractCompiler(),
    )

    report = service.validate_draft(
        draft, source_columns=["Material", "ProductionPlant", "Qty"], target_columns=["PRDID", "LOCID", "QTY"],
        source_sample=source_df, target_sample=target_df,
    )
    assert report["ok"], report

    contract = service.approve_contract(draft, approved_by="alice")

    for _ in range(2):  # determinism: same result on repeated runs
        out = service.run_reconciliation(
            contract_id=contract.contract_id,
            source_snapshot_id=src_snap.snapshot_id,
            target_snapshot_id=tgt_snap.snapshot_id,
        )
        summary = out["summary"]
        assert summary["match"] == 1
        assert summary["quantity_mismatch"] == 0
        assert summary["mismatch"] == 0  # held-out rows never counted here
        assert summary["excluded_unmapped"]["Material"] == 1  # MAT-B, MEDIUM
        assert summary["excluded_unmapped"]["ProductionPlant"] == 1  # PL99, NONE


# ── full lifecycle ─────────────────────────────────────────────────────────

def test_full_compile_validate_approve_reconcile():
    source_df = pd.DataFrame({"id": ["A", "B", "C"], "qty": [10, 20, 30]})
    target_df = pd.DataFrame({"id": ["A", "B", "D"], "qty": [10, 25, 40]})

    src_snap = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="s4")
    tgt_snap = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="ibp")

    draft = _draft()
    report = service.validate_draft(
        draft,
        source_columns=["id", "qty"],
        target_columns=["id", "qty"],
        source_sample=source_df,
        target_sample=target_df,
    )
    assert report["ok"], report

    contract = service.approve_contract(draft, approved_by="alice")
    assert contract.is_executable()
    assert contract.contract_version == 1

    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
    )
    summary = out["summary"]
    assert summary["match"] == 1
    assert summary["quantity_mismatch"] == 1
    assert summary["mismatch"] == 2


def test_cannot_run_unapproved_contract():
    source_df = pd.DataFrame({"id": ["A"], "qty": [1]})
    src_snap = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="s4")
    tgt_snap = service.ingest_snapshot(source_df, layer=RawLayer.TARGET, source_type="ibp")

    with pytest.raises(ValueError):
        service.run_reconciliation(
            contract_id="does_not_exist",
            source_snapshot_id=src_snap.snapshot_id,
            target_snapshot_id=tgt_snap.snapshot_id,
        )


def test_approval_versions_increment():
    draft = _draft()
    c1 = service.approve_contract(draft, approved_by="alice", contract_id="fixed")
    c2 = service.approve_contract(draft, approved_by="bob", contract_id="fixed")
    assert c1.contract_version == 1
    assert c2.contract_version == 2


def test_audit_trail_recorded():
    from backend.recon_engine.storage import audit_store

    source_df = pd.DataFrame({"id": ["A"], "qty": [1]})
    service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="s4")
    events = audit_store.list_events()
    assert any(e.action.value == "snapshot_created" for e in events)
