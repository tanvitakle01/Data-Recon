"""Review-Changes checkpoint: shadow preview + diffs + fingerprint guard.

Exercises the read-only shadow-preview path and the deterministic fingerprint
verification that protects reconciliation from running a shadow the user never
reviewed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.recon_engine import service
from backend.recon_engine.compiler import StubContractCompiler
from backend.recon_engine.models.snapshot import RawLayer


def _approved_contract_and_snapshots():
    """Objective's Plant/Material example: transforms align source to target."""
    source_df = pd.DataFrame({"Plant": ["5006"], "Material": ["N01-FG01"], "Qty": [100]})
    target_df = pd.DataFrame({"LOCID": ["PL5006@S21400"], "PRDID": ["T01-FG01"], "QTY": [100]})
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
    contract = service.approve_contract(draft, approved_by="alice")
    return contract, src_snap, tgt_snap


def test_shadow_preview_reports_transformed_values_and_diffs():
    contract, src_snap, tgt_snap = _approved_contract_and_snapshots()

    preview = service.build_shadow_preview(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
    )

    # Shadow shows the transformed values.
    assert preview["shadow"]["rows"][0]["Plant"] == "PL5006@S21400"
    assert preview["shadow"]["rows"][0]["Material"] == "T01-FG01"
    # Original is preserved untouched.
    assert preview["source"]["rows"][0]["Plant"] == "5006"

    # Row-level diff flags the changed fields and leaves Qty unchanged.
    changes = {c["field"]: c for c in preview["diffs"][0]["changes"]}
    assert changes["Plant"]["before"] == "5006"
    assert changes["Plant"]["after"] == "PL5006@S21400"
    assert changes["Plant"]["changed"] is True
    assert changes["Plant"]["kind"] == "modified"
    assert changes["Qty"]["changed"] is False

    # Target preview + fingerprint present.
    assert preview["target"]["rows"][0]["LOCID"] == "PL5006@S21400"
    assert isinstance(preview["shadow_fingerprint"], str) and preview["shadow_fingerprint"]
    assert preview["operations"], "contract operations should be surfaced for review"


def test_shadow_preview_is_read_only_no_run_created():
    contract, src_snap, tgt_snap = _approved_contract_and_snapshots()
    from backend.recon_engine.storage import run_store

    before = len(run_store.list_runs()) if hasattr(run_store, "list_runs") else None
    service.build_shadow_preview(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
    )
    if before is not None:
        assert len(run_store.list_runs()) == before


def test_run_accepts_matching_fingerprint():
    contract, src_snap, tgt_snap = _approved_contract_and_snapshots()
    preview = service.build_shadow_preview(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
    )
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
        expected_shadow_fingerprint=preview["shadow_fingerprint"],
    )
    assert out["summary"]["match"] == 1


def test_rows_as_records_truncates_long_cells():
    long_text = "x" * 500
    df = pd.DataFrame({"note": [long_text], "qty": [100]})
    rows = service._rows_as_records(df, limit=10, max_chars=50)
    assert rows[0]["note"] == "x" * 50 + "…"
    # Non-string cells pass through untouched.
    assert rows[0]["qty"] == 100


def test_rows_as_records_no_truncation_when_disabled():
    df = pd.DataFrame({"note": ["hello world"]})
    rows = service._rows_as_records(df, limit=10, max_chars=0)
    assert rows[0]["note"] == "hello world"


def test_run_rejects_stale_fingerprint():
    contract, src_snap, tgt_snap = _approved_contract_and_snapshots()
    with pytest.raises(service.ShadowFingerprintMismatch):
        service.run_reconciliation(
            contract_id=contract.contract_id,
            source_snapshot_id=src_snap.snapshot_id,
            target_snapshot_id=tgt_snap.snapshot_id,
            expected_shadow_fingerprint="sha256:not-the-real-one",
        )
