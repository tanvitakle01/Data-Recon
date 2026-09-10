"""Coverage for the unified insights pipeline (backend.recon_engine.insights):
- `normalize.from_run` produces correct break-rate/hotspot/variance facts for
  a run carrying all four record classes (match, quantity mismatch, missing
  in target, missing in source);
- `normalize.from_workbook`, reading back the exact workbook
  `service.build_comparison_workbook` exports for that same run, converges on
  the identical break-rate facts — proving the run-based and upload-based
  entry points are genuinely one pipeline;
- `facts.py`'s pure aggregation helpers and `query.py`'s drill-through
  filters, exercised directly against small hand-built frames.
"""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from backend.recon_engine import service
from backend.recon_engine.compiler import StubContractCompiler
from backend.recon_engine.engine.executor import build_shadow_source
from backend.recon_engine.engine.reconciler import reconcile
from backend.recon_engine.insights import builder as insights_builder
from backend.recon_engine.insights import facts, normalize, query
from backend.recon_engine.models.run import ReconciliationRun, RunStatus
from backend.recon_engine.models.snapshot import RawLayer
from backend.recon_engine.storage import result_store, run_store


def _run_with_all_four_statuses() -> str:
    graph_run_id = "test_insights_all_statuses"

    source_df = pd.DataFrame({"Material": ["M1", "M2", "M3"], "Qty": [10, 20, 30]})
    target_df = pd.DataFrame({"Material": ["M1", "M2", "M4"], "TargetQty": [10, 25, 40]})

    service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")

    draft, _ = service.compile_draft(
        mapping_sheet=[
            {"source_col": "Material", "target_col": "Material", "role": "key"},
            {"source_col": "Qty", "target_col": "TargetQty", "role": "compare"},
        ],
        rules="",
        business_key=[{"source_field": "Material", "target_field": "Material"}],
        compare_fields=[{"source_field": "Qty", "target_field": "TargetQty"}],
        value_mappings=[],
        source_schema=["Material", "Qty"],
        target_schema=["Material", "TargetQty"],
        comparison_type="c", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )
    contract = service.approve_contract(draft, approved_by="alice")

    built = build_shadow_source(contract, source_df)
    recon = reconcile(contract, built.shadow_df, target_df)
    recon.detail_df = service.attach_field_values(
        recon.detail_df, contract, shadow_df=built.shadow_df, target_df=target_df, raw_source_df=source_df,
    )

    detail_df = recon.detail_df.copy()
    detail_df["run_id"] = graph_run_id
    detail_df["batch_id"] = "batch_1"
    detail_df["record_id"] = [f"rec_{i}" for i in range(len(detail_df))]

    result = result_store.start_streaming_result(
        run_id=graph_run_id, contract_id=contract.contract_id, contract_version=contract.contract_version,
    )
    result_store.append_batch_result(result.result_id, detail_df=detail_df, batch_summary=recon.summary)

    run = ReconciliationRun(
        run_id=graph_run_id,
        contract_id=contract.contract_id,
        contract_version=contract.contract_version,
        source_snapshot_id=f"streaming:{graph_run_id}",
        target_snapshot_id=f"streaming:{graph_run_id}",
        status=RunStatus.COMPLETED,
        created_by="test",
    )
    run_store.save_run(run)
    return graph_run_id


def test_run_based_break_rate_counts_all_four_statuses():
    run_id = _run_with_all_four_statuses()
    payload = insights_builder.build_for_run(run_id)

    break_rate = payload["breakRate"]
    assert break_rate["total"] == 4
    counts = {r["key"]: r["count"] for r in break_rate["results"]}
    assert counts == {"match": 1, "quantity_mismatch": 1, "missing_in_target": 1, "missing_in_source": 1}
    # Delta convention: absent side treated as 0 (service._signed_delta) —
    # M2: 20-25=-5, M3 (missing in target): 30-0=30, M4 (missing in source): 0-40=-40.
    assert break_rate["netDelta"] == pytest.approx(-15.0)
    assert break_rate["totalAbsoluteVariance"] == pytest.approx(75.0)


def test_run_based_hotspots_rank_every_breaking_material():
    run_id = _run_with_all_four_statuses()
    payload = insights_builder.build_for_run(run_id)

    material_section = next(s for s in payload["hotspots"] if s["label"] == "Material")
    by_value = {r["value"]: r for r in material_section["rows"]}
    assert set(by_value) == {"M2", "M3", "M4"}  # M1 (match) never appears — 0 breaks
    assert by_value["M3"]["absQtyVariance"] == pytest.approx(30.0)
    assert by_value["M4"]["absQtyVariance"] == pytest.approx(40.0)


def test_upload_workbook_converges_with_run_based_facts():
    """The exported workbook's Status column carries missing_in_target and
    missing_in_source as distinct statuses — normalize.from_workbook must
    recover the exact same 4-way split reading them back directly.

    netDelta is the one fact that can't converge: the workbook's own Delta
    column always shows the non-negative magnitude (see
    service._signed_delta's docstring), so re-deriving netDelta from an
    upload necessarily loses the sign and lands on totalAbsoluteVariance
    instead of the live run's signed net. That's an accepted, deliberate
    trade-off, not a bug — only the run-based path can recover the true
    signed net."""
    run_id = _run_with_all_four_statuses()
    workbook_bytes = service.build_comparison_workbook(run_id)

    run_payload = insights_builder.build_for_run(run_id)
    upload_payload = insights_builder.build_for_upload(workbook_bytes)

    run_counts = {r["key"]: r["count"] for r in run_payload["breakRate"]["results"]}
    upload_counts = {r["key"]: r["count"] for r in upload_payload["breakRate"]["results"]}
    assert run_counts == upload_counts

    assert run_payload["breakRate"]["netDelta"] == pytest.approx(-15.0)
    assert upload_payload["breakRate"]["netDelta"] == pytest.approx(
        upload_payload["breakRate"]["totalAbsoluteVariance"]
    )
    assert upload_payload["breakRate"]["totalAbsoluteVariance"] == pytest.approx(
        run_payload["breakRate"]["totalAbsoluteVariance"]
    )
    assert upload_payload["uploadId"]  # stashed for a later drill-through/PDF call


def test_from_workbook_rejects_an_unrecognized_file():
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "Sheet1"
    buf = BytesIO()
    wb.save(buf)

    with pytest.raises(normalize.UnrecognizedWorkbookError):
        normalize.from_workbook(buf.getvalue())


# ── pure facts.py unit tests (no storage) ────────────────────────────────────


def test_unmapped_by_field_counts_paired_and_unpaired():
    mapping_df = pd.DataFrame(
        {
            "Mapping": ["Material → PRDID", "Material → PRDID", "Plant → LOCID"],
            "Source Value": ["A", "B", "P1"],
            "Status": ["Paired", "Unpaired", "Paired"],
        }
    )
    rows = facts._unmapped_by_field(mapping_df)
    by_label = {r["label"]: r for r in rows}
    assert by_label["Material → PRDID"] == {
        "label": "Material → PRDID", "unpaired": 1, "paired": 1, "total": 2,
        "filter": {"kind": "mappingUnpaired", "mapping": "Material → PRDID"},
    }
    assert by_label["Plant → LOCID"]["unpaired"] == 0


def test_variance_distribution_bins_nonzero_magnitudes_only():
    magnitudes = pd.Series([0.0, 0.0, 5.0, 10.0, 50.0, 100.0])
    bins = facts._variance_distribution(magnitudes)
    assert bins  # non-empty
    assert sum(b["count"] for b in bins) == 4  # zeros excluded


def test_date_coverage_splits_source_and_target_windows_by_status():
    df = pd.DataFrame(
        {
            "Date": ["2024-01-01", "2024-01-05", "2024-01-10", "2024-01-20"],
            "__status__": [
                normalize.STATUS_MATCH,
                normalize.STATUS_QTY_MISMATCH,
                normalize.STATUS_MISSING_IN_TARGET,
                normalize.STATUS_MISSING_IN_SOURCE,
            ],
        }
    )
    coverage = facts._date_coverage(df, {"Date": ["Date"]}, compare_pairs=[])
    assert coverage["sourceMin"] == "2024-01-01"
    assert coverage["sourceMax"] == "2024-01-10"  # excludes the 01-20 target-only row
    assert coverage["targetMin"] == "2024-01-01"
    assert coverage["targetMax"] == "2024-01-20"  # excludes the 01-10 source-only row
    assert coverage["sourceDatesOutsideTargetWindow"] == 0
    assert coverage["targetDatesOutsideSourceWindow"] == 1  # 01-20 falls outside source's 01-01..01-10 window


# ── query.py drill-through ────────────────────────────────────────────────────


def _small_normalized() -> normalize.NormalizedRecon:
    records_df = pd.DataFrame(
        {
            "Material": ["M1", "M2", "M3"],
            "Delta": [0.0, -5.0, 30.0],
            "__status__": [normalize.STATUS_MATCH, normalize.STATUS_QTY_MISMATCH, normalize.STATUS_MISSING_IN_TARGET],
            "Status Detail": ["Match", "Quantity Mismatch", "Missing in Target"],
        }
    )
    return normalize.NormalizedRecon(
        run_id="r1", upload_id=None, total=3, records_df=records_df, mapping_df=pd.DataFrame(),
        delta_columns=["Delta"], compare_pairs=[], dimension_columns={"Material": ["Material"]}, key_columns=["Material"],
    )


def test_filter_records_by_status():
    normalized = _small_normalized()
    result = query.filter_records(normalized, {"kind": "status", "value": normalize.STATUS_QTY_MISMATCH})
    assert result["totalMatched"] == 1
    assert result["rows"][0]["Material"] == "M2"


def test_filter_records_by_dimension():
    normalized = _small_normalized()
    result = query.filter_records(normalized, {"kind": "dimension", "field": "Material", "value": "M3"})
    assert result["totalMatched"] == 1
    assert result["rows"][0]["__status__"] == normalize.STATUS_MISSING_IN_TARGET


def test_filter_records_by_variance_bin():
    normalized = _small_normalized()
    result = query.filter_records(normalized, {"kind": "varianceBin", "min": 4.0, "max": 40.0})
    values = {r["Material"] for r in result["rows"]}
    assert values == {"M2", "M3"}


def test_filter_records_by_date_outside_window():
    records_df = pd.DataFrame(
        {
            "Date": ["2024-01-01", "2024-01-05", "2024-01-10", "2024-01-20"],
            "__status__": [
                normalize.STATUS_MATCH,
                normalize.STATUS_QTY_MISMATCH,
                normalize.STATUS_MISSING_IN_TARGET,
                normalize.STATUS_MISSING_IN_SOURCE,
            ],
        }
    )
    normalized = normalize.NormalizedRecon(
        run_id="r1", upload_id=None, total=4, records_df=records_df, mapping_df=pd.DataFrame(),
        delta_columns=[], compare_pairs=[], dimension_columns={"Date": ["Date"]}, key_columns=["Date"],
    )
    result = query.filter_records(normalized, {"kind": "dateOutsideWindow", "side": "target"})
    assert result["totalMatched"] == 1
    assert result["rows"][0]["Date"] == "2024-01-20"


def test_records_to_csv_round_trips():
    normalized = _small_normalized()
    csv_text = query.records_to_csv(normalized, {"kind": "status", "value": normalize.STATUS_MATCH})
    assert "M1" in csv_text
    assert "M2" not in csv_text
