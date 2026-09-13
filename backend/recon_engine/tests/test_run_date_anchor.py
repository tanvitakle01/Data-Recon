"""Coverage for the run-time anchor override (``anchor_date``) added to
``service.run_reconciliation``/``build_shadow_preview`` and the run's
persisted ``anchor_date``/``anchor_resolver``.

Real-world motivation (the second half of the 5CIR ECC->IBP bug): a
``relative_date_reassign`` "roll a past-due date forward to tomorrow" rule is
anchored to wall-clock "now" by default — correct for a live run where
source and target are both freshly pulled today, but a STATIC target extract
captured on an earlier day can never match a rule computed against any OTHER
day. ``anchor_date`` lets a caller replay the contract as if it ran on the
day the target extract was actually captured, instead of silently comparing
against whatever day happens to be "today" when the test/validation runs.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.recon_engine import service
from backend.recon_engine.compiler import StubContractCompiler
from backend.recon_engine.models.snapshot import RawLayer
from backend.recon_engine.storage import run_store


def _rollforward_contract_and_snapshots():
    """A tiny stand-in for the real VBBE->SOPDD_STAGING_KFTAB rule: a source
    date safely in the past (2020-01-01) always satisfies "lt anchor", so it
    always gets reassigned to anchor + 1 day — deterministic regardless of
    which real calendar day the test suite happens to run on."""
    source_df = pd.DataFrame({
        "PRDID": ["786293"], "LOCID": ["3340"], "KEYFIGUREDATE": ["2020-01-01"], "QTY": [5],
    })
    # Frozen target extract: whoever captured this ran the rule anchored to
    # 2026-01-01, so its KEYFIGUREDATE is fixed at 2026-01-02 forever after.
    target_df = pd.DataFrame({
        "PRDID": ["786293"], "LOCID": ["3340"], "KEYFIGUREDATE": ["2026-01-02"], "QTY": [5],
    })
    src_snap = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt_snap = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")

    mapping_sheet = [
        {"source_col": "PRDID", "target_col": "PRDID", "role": "key"},
        {"source_col": "LOCID", "target_col": "LOCID", "role": "key"},
        {"source_col": "KEYFIGUREDATE", "target_col": "KEYFIGUREDATE", "role": "key"},
        {"source_col": "QTY", "target_col": "QTY", "role": "compare"},
    ]
    draft, _ = service.compile_draft(
        mapping_sheet=mapping_sheet, rules="",
        business_key=[
            {"source_field": "PRDID", "target_field": "PRDID"},
            {"source_field": "LOCID", "target_field": "LOCID"},
            {"source_field": "KEYFIGUREDATE", "target_field": "KEYFIGUREDATE"},
        ],
        compare_fields=[{"source_field": "QTY", "target_field": "QTY"}],
        source_schema=list(source_df.columns), target_schema=list(target_df.columns),
        comparison_type="custom", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )
    draft.operations = [
        {
            "op": "date_window_filter", "field": "KEYFIGUREDATE",
            "params": {"lower_offset_days": -3650, "upper_offset_days": 3650},
        },
        {
            "op": "relative_date_reassign", "field": "KEYFIGUREDATE",
            "params": {"date_condition": "lt", "offset_days": 1},
        },
    ]
    contract = service.approve_contract(draft, approved_by="alice")
    return contract, src_snap, tgt_snap


def test_matching_anchor_date_reconciles_a_static_target_extract():
    """The core fix: an explicit anchor matching the day the target extract
    was captured makes the rollforward rule reproduce the target's frozen
    date, so the run matches."""
    contract, src_snap, tgt_snap = _rollforward_contract_and_snapshots()
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
        anchor_date="2026-01-01",
    )
    assert out["summary"]["match"] == 1
    assert out["summary"]["quantity_mismatch"] == 0
    assert out["summary"]["missing_in_target"] == 0
    assert out["summary"]["extra_in_target"] == 0


def test_wrong_anchor_date_reproduces_the_zero_match_symptom():
    """Anchoring to a DIFFERENT day than the target extract was captured on
    reproduces exactly the reported bug: the key's date component no longer
    lines up, so nothing matches — even though every other field is
    identical. This is the expected, correct behavior (a genuine data/timing
    fact), not something the fix should paper over."""
    contract, src_snap, tgt_snap = _rollforward_contract_and_snapshots()
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
        anchor_date="2026-02-01",
    )
    assert out["summary"]["match"] == 0
    assert out["summary"]["missing_in_target"] == 1
    assert out["summary"]["extra_in_target"] == 1


def test_run_persists_explicit_anchor_and_resolver():
    contract, src_snap, tgt_snap = _rollforward_contract_and_snapshots()
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
        anchor_date="2026-01-01",
    )
    run = run_store.get_run(out["run_id"])
    assert run is not None
    assert run.anchor_resolver == "explicit"
    assert run.anchor_date is not None
    assert run.anchor_date.date().isoformat() == "2026-01-01"


def test_run_without_anchor_date_infers_it_from_the_frozen_target():
    """The actual gap this closes: nobody has to work out by hand which day
    a static target extract was captured on and pass it as ``anchor_date`` —
    the target's own KEYFIGUREDATE value already carries the rollforward
    rule's output, so the anchor is recovered by inverting that rule against
    it (see ``engine.anchor_inference``), with no date/weekday hardcoded
    anywhere in the inference itself."""
    contract, src_snap, tgt_snap = _rollforward_contract_and_snapshots()
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
    )
    run = run_store.get_run(out["run_id"])
    assert run is not None
    assert run.anchor_resolver == "inferred_from_target"
    assert run.anchor_date is not None
    assert run.anchor_date.date().isoformat() == "2026-01-01"
    # The inferred anchor reproduces the target's frozen date, so the run
    # matches automatically — no anchor_date argument required at all.
    assert out["summary"]["match"] == 1
    assert out["anchor_inference"]["confidence"] == 1.0


def test_run_without_anchor_date_or_rollforward_rule_falls_back_to_wall_clock():
    """A contract with no ``relative_date_reassign`` rule has nothing for
    inference to invert — omitting ``anchor_date`` must still behave exactly
    like a normal live run (both sides freshly pulled "today")."""
    source_df = pd.DataFrame({"PRDID": ["786293"], "LOCID": ["3340"], "QTY": [5]})
    target_df = pd.DataFrame({"PRDID": ["786293"], "LOCID": ["3340"], "QTY": [5]})
    src_snap = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt_snap = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")

    mapping_sheet = [
        {"source_col": "PRDID", "target_col": "PRDID", "role": "key"},
        {"source_col": "LOCID", "target_col": "LOCID", "role": "key"},
        {"source_col": "QTY", "target_col": "QTY", "role": "compare"},
    ]
    draft, _ = service.compile_draft(
        mapping_sheet=mapping_sheet, rules="",
        business_key=[
            {"source_field": "PRDID", "target_field": "PRDID"},
            {"source_field": "LOCID", "target_field": "LOCID"},
        ],
        compare_fields=[{"source_field": "QTY", "target_field": "QTY"}],
        source_schema=list(source_df.columns), target_schema=list(target_df.columns),
        comparison_type="custom", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )
    contract = service.approve_contract(draft, approved_by="alice")

    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
    )
    run = run_store.get_run(out["run_id"])
    assert run is not None
    assert run.anchor_resolver == "wall_clock"
    # Still populated (with whatever "now" actually was), never left blank.
    assert run.anchor_date is not None
    # Inference was still attempted (and its reason recorded, for audit) —
    # it just found nothing to invert, which is why wall-clock was used.
    assert out["anchor_inference"]["anchor_date"] is None
    assert out["anchor_inference"]["reason"] is not None


def test_tied_anchor_inference_falls_back_to_wall_clock():
    """A target date that inverts to two EQUALLY self-consistent anchor
    candidates (see test_anchor_inference.
    test_tied_candidates_yield_exactly_half_confidence_not_a_silent_guess)
    must not be silently resolved to either one — an exact tie isn't
    confident enough to prefer over the live wall-clock default."""
    source_df = pd.DataFrame({
        "PRDID": ["786293"], "LOCID": ["3340"], "KEYFIGUREDATE": ["2020-01-01"], "QTY": [5],
    })
    target_df = pd.DataFrame({
        "PRDID": ["786293"], "LOCID": ["3340"], "KEYFIGUREDATE": ["2026-01-05"], "QTY": [5],
    })
    src_snap = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt_snap = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")

    mapping_sheet = [
        {"source_col": "PRDID", "target_col": "PRDID", "role": "key"},
        {"source_col": "LOCID", "target_col": "LOCID", "role": "key"},
        {"source_col": "KEYFIGUREDATE", "target_col": "KEYFIGUREDATE", "role": "key"},
        {"source_col": "QTY", "target_col": "QTY", "role": "compare"},
    ]
    draft, _ = service.compile_draft(
        mapping_sheet=mapping_sheet, rules="",
        business_key=[
            {"source_field": "PRDID", "target_field": "PRDID"},
            {"source_field": "LOCID", "target_field": "LOCID"},
            {"source_field": "KEYFIGUREDATE", "target_field": "KEYFIGUREDATE"},
        ],
        compare_fields=[{"source_field": "QTY", "target_field": "QTY"}],
        source_schema=list(source_df.columns), target_schema=list(target_df.columns),
        comparison_type="custom", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )
    draft.operations = [
        {
            "op": "relative_date_reassign", "field": "KEYFIGUREDATE",
            "params": {
                "date_condition": "lt", "offset_days": 1,
                "weekday_exception": {"on_weekday": "Saturday", "offset_days": 2},
            },
        },
    ]
    contract = service.approve_contract(draft, approved_by="alice")

    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
    )
    run = run_store.get_run(out["run_id"])
    assert run is not None
    assert run.anchor_resolver == "wall_clock"
    assert out["anchor_inference"]["confidence"] == 0.5


def test_shadow_preview_respects_anchor_date_and_reports_it():
    contract, src_snap, tgt_snap = _rollforward_contract_and_snapshots()
    preview = service.build_shadow_preview(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
        anchor_date="2026-01-01",
    )
    assert preview["shadow"]["rows"][0]["KEYFIGUREDATE"] == "2026-01-02"
    assert preview["anchor_date"] == "2026-01-01"
    assert preview["anchor_resolver"] == "explicit"


def test_shadow_preview_without_anchor_date_also_infers_it_from_target():
    """Preview and run must agree on the same inferred anchor for the same
    (contract, target) pair — otherwise the Review-Changes fingerprint guard
    would spuriously reject a run that never actually diverged from what was
    previewed."""
    contract, src_snap, tgt_snap = _rollforward_contract_and_snapshots()
    preview = service.build_shadow_preview(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
    )
    assert preview["anchor_date"] == "2026-01-01"
    assert preview["anchor_resolver"] == "inferred_from_target"
    assert preview["anchor_inference"]["confidence"] == 1.0

    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
        expected_shadow_fingerprint=preview["shadow_fingerprint"],
    )
    assert out["summary"]["match"] == 1


def test_run_rejects_a_different_anchor_than_the_reviewed_preview_used():
    """The Review-Changes fingerprint guard must catch an anchor_date that
    changed between preview and run, exactly like it catches a changed
    contract or source snapshot — the anchor is part of what was reviewed."""
    contract, src_snap, tgt_snap = _rollforward_contract_and_snapshots()
    preview = service.build_shadow_preview(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
        anchor_date="2026-01-01",
    )
    with pytest.raises(service.ShadowFingerprintMismatch):
        service.run_reconciliation(
            contract_id=contract.contract_id,
            source_snapshot_id=src_snap.snapshot_id,
            target_snapshot_id=tgt_snap.snapshot_id,
            expected_shadow_fingerprint=preview["shadow_fingerprint"],
            anchor_date="2026-02-01",
        )


def test_compute_run_date_alignment_flags_zero_overlap_for_the_wrong_anchor():
    contract, src_snap, tgt_snap = _rollforward_contract_and_snapshots()
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
        anchor_date="2026-02-01",
    )
    run = run_store.get_run(out["run_id"])
    alignment = service.compute_run_date_alignment(run)
    assert alignment["has_overlap"] is False
    assert alignment["source_range"]["start"] == "2026-02-02"
    assert alignment["target_range"]["start"] == "2026-01-02"


def test_compute_run_date_alignment_confirms_overlap_for_the_right_anchor():
    contract, src_snap, tgt_snap = _rollforward_contract_and_snapshots()
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
        anchor_date="2026-01-01",
    )
    run = run_store.get_run(out["run_id"])
    alignment = service.compute_run_date_alignment(run)
    assert alignment["has_overlap"] is True
