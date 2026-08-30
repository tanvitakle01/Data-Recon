"""service.build_simple_insights: the direct, honest insights payload that
replaced the legacy Remarks-bridge + InsightEngine for real reconciliation
runs (see routes/insights.py's /insights/from-run-id)."""

from __future__ import annotations

import pandas as pd

from backend.recon_engine import service
from backend.recon_engine.compiler import StubContractCompiler
from backend.recon_engine.models.snapshot import RawLayer


def _completed_run() -> str:
    # Same fixture shape as test_comparison_export.py's _completed_run: Material
    # -> PRDID (A matches via value mapping, B is a quantity mismatch, C is
    # missing in target), Plant -> LOCID (identity), a date key, one compare
    # field. D (present only in target) rounds out the mismatch bucket.
    source_df = pd.DataFrame({
        "Material": ["A", "B", "C"],
        "Plant": ["P1", "P1", "P1"],
        "Date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "ReqQty": [10, 20, 30],
    })
    target_df = pd.DataFrame({
        "PRDID": ["PA", "B", "D"],
        "LOCID": ["LOC1", "LOC1", "LOC1"],
        "Date": ["2024-01-01", "2024-01-02", "2024-01-04"],
        "SalesOrderRequest": [10, 25, 40],
    })
    src = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")
    draft, _ = service.compile_draft(
        mapping_sheet=[
            {"source_col": "Material", "target_col": "PRDID", "role": "key"},
            {"source_col": "Plant", "target_col": "LOCID", "role": "key"},
            {"source_col": "Date", "target_col": "Date", "role": "key"},
            {"source_col": "ReqQty", "target_col": "SalesOrderRequest", "role": "compare"},
        ],
        rules="",
        business_key=[
            {"source_field": "Material", "target_field": "PRDID"},
            {"source_field": "Plant", "target_field": "LOCID"},
            {"source_field": "Date", "target_field": "Date"},
        ],
        compare_fields=[{"source_field": "ReqQty", "target_field": "SalesOrderRequest"}],
        value_mappings=[
            {
                "source_field": "Material",
                "target_field": "PRDID",
                "matches": [
                    {"source_value": "A", "target_value": "PA", "confidence": "high",
                     "rule": "t", "evidence": "e"},
                    {"source_value": "B", "target_value": "B", "confidence": "very_high",
                     "rule": "t", "evidence": "e"},
                    {"source_value": "C", "target_value": "C", "confidence": "very_high",
                     "rule": "t", "evidence": "e"},
                ],
            },
            {
                "source_field": "Plant",
                "target_field": "LOCID",
                "matches": [
                    {"source_value": "P1", "target_value": "LOC1", "confidence": "high",
                     "rule": "t", "evidence": "e"},
                ],
            },
        ],
        source_schema=["Material", "Plant", "Date", "ReqQty"],
        target_schema=["PRDID", "LOCID", "Date", "SalesOrderRequest"],
        comparison_type="c", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )
    contract = service.approve_contract(draft, approved_by="alice")
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src.snapshot_id,
        target_snapshot_id=tgt.snapshot_id,
    )
    return out["run_id"]


def test_results_breakdown_matches_summary():
    run_id = _completed_run()
    payload = service.build_simple_insights(run_id)

    assert payload["runId"] == run_id
    assert payload["total"] == 4

    by_key = {r["key"]: r for r in payload["results"]}
    assert by_key["match"]["count"] == 1 and by_key["match"]["pct"] == 25.0
    assert by_key["match"]["status"] == "MATCH"
    assert by_key["quantity_mismatch"]["count"] == 1 and by_key["quantity_mismatch"]["pct"] == 25.0
    assert by_key["quantity_mismatch"]["status"] == "QUANTITY MISMATCH"
    assert by_key["mismatch"]["count"] == 2 and by_key["mismatch"]["pct"] == 50.0
    assert by_key["mismatch"]["status"] == "MISMATCH"


def test_quantity_variance_rolls_up_only_real_field_diffs():
    run_id = _completed_run()
    payload = service.build_simple_insights(run_id)

    # Only B (20 vs 25) is a field-level compare failure — C/D are missing on
    # one side entirely, which never runs the compare-field diff at all.
    assert payload["quantityVariance"] == {"totalUnits": 5.0, "largestUnit": 5.0, "fieldsAffected": 1}


def test_mapping_match_rates_reflect_value_mapping_library():
    run_id = _completed_run()
    payload = service.build_simple_insights(run_id)

    by_label = {m["label"]: m for m in payload["mappings"]}
    assert by_label["Material → PRDID"]["matched"] == 3
    assert by_label["Material → PRDID"]["unmatched"] == 0
    assert by_label["Plant → LOCID"]["matched"] == 1
    assert by_label["Plant → LOCID"]["unmatched"] == 0
    # Date is a plain key with no value mapping — never surfaced as a mapping.
    assert not any(m["label"].startswith("Date") for m in payload["mappings"])


def test_exceptions_exclude_matches_and_carry_all_records_columns():
    run_id = _completed_run()
    payload = service.build_simple_insights(run_id)

    exceptions = payload["exceptions"]
    assert "Status" in exceptions["columns"]
    statuses = [row["Status"] for row in exceptions["rows"]]
    assert sorted(statuses) == ["MISMATCH", "MISMATCH", "QUANTITY MISMATCH"]
    assert "MATCH" not in statuses


def test_unknown_run_raises_key_error():
    try:
        service.build_simple_insights("run_does_not_exist")
        assert False, "expected KeyError"
    except KeyError:
        pass
