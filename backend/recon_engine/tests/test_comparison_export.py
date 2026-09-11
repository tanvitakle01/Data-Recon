"""Comparison-sheet export: service.build_comparison_workbook + the route."""

from __future__ import annotations

from io import BytesIO

import openpyxl
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recon_engine import service
from backend.recon_engine.compiler import StubContractCompiler
from backend.recon_engine.models.snapshot import RawLayer
from backend.routes.recon_v2 import router


def _completed_run() -> str:
    # Realistic app schema: Material -> PRDID, Plant -> LOCID, a date key, and
    # a single quantity compare field (ReqQty -> SalesOrderRequest) — the
    # fixed shape build_enriched_detail's export-column roles key off of.
    # Material "A" is VALUE-MAPPED to a different PRDID ("PA") so the raw
    # OriginalMaterial and the paired OriginalPRDID genuinely differ; "B"/"C"
    # resolve by identity.
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


def _chart_title(chart) -> str:
    return chart.title.tx.rich.p[0].r[0].t


def test_build_comparison_workbook_is_three_sheets():
    run_id = _completed_run()
    content = service.build_comparison_workbook(run_id)
    wb = openpyxl.load_workbook(BytesIO(content))
    assert wb.sheetnames == ["Summary", "All Records", "Transformations Applied"]

    # ── All Records: a Source + Target column per business-key pair (every
    # key pair, not just value-mapped ones), headed with the contract's own
    # field names — never suffixed with "(Source)"/"(Target)" even when the
    # two sides share one name (here, Date): column order alone conveys which
    # side is which, so a colliding pair renders as two plainly, identically
    # headed columns holding their own distinct values. A Pair ID sits right
    # after each value-mapped key pair, then the compare fields (source,
    # target, Delta — always non-negative), then "Status" always last. No
    # more Run ID/Batch ID/Record ID.
    ws = wb["All Records"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == (
        "Material", "PRDID", "Material Pair ID",
        "Plant", "LOCID", "Plant Pair ID",
        "Date", "Date",
        "ReqQty", "SalesOrderRequest", "Delta", "Status",
    )

    data = rows[1:]
    statuses = [r[11] for r in data]
    # Dataset -> A match, B quantity mismatch, C missing-in-target (source
    # only), D extra-in-target (target only) — each its own Status now.
    # Sort order: quantity mismatch, missing in target, extra in target, match.
    assert statuses == ["QUANTITY MISMATCH", "MISSING IN TARGET", "EXTRA IN TARGET", "MATCH"]

    by_prdid_or_material = {(r[0], r[1]): r for r in data}

    # Match (A): raw Material differs from the paired PRDID — both sides
    # visible side by side — Delta is 0 (10 - 10).
    match = by_prdid_or_material[("A", "PA")]
    assert match[3] == "P1" and match[4] == "LOC1"
    assert match[6] == "2024-01-01" and match[7] == "2024-01-01"
    assert match[8] == 10 and match[9] == 10 and match[10] == 0

    # Quantity Mismatch (B): identity-mapped Material/Plant, Delta is the
    # non-negative magnitude of 20 - 25.
    mm = by_prdid_or_material[("B", "B")]
    assert mm[8] == 20 and mm[9] == 25 and mm[10] == 5

    # Missing in Target (C, source only): no target row exists at all, so
    # every Target-side column is blank; Delta convention treats the absent
    # target side as 0 -> Delta == ReqQty.
    missing = by_prdid_or_material[("C", None)]
    assert missing[3] == "P1" and missing[4] is None
    assert missing[6] == "2024-01-03" and missing[7] is None
    assert missing[8] == 30 and missing[9] is None and missing[10] == 30

    # Extra in Target (D, target only): no source row exists at all, so
    # every Source-side column is blank; Delta == SalesOrderRequest (always
    # non-negative, so the absent source side doesn't make it negative).
    extra = by_prdid_or_material[(None, "D")]
    assert extra[3] is None and extra[4] == "LOC1"
    assert extra[6] is None and extra[7] == "2024-01-04"
    assert extra[8] is None and extra[9] == 40 and extra[10] == 40

    # Pair ID (see recon_engine.ids) stays blank for this Manual-mode run,
    # which has no per-row pair identity of its own.
    for r in data:
        assert r[2] is None and r[5] is None

    # Whole row filled with the status colour (amber/red/blue).
    qty_row = statuses.index("QUANTITY MISMATCH") + 2  # +1 header, +1 to 1-index
    assert ws.cell(row=qty_row, column=1).fill.fgColor.rgb.endswith("FFEB9C")
    assert ws.cell(row=qty_row, column=9).fill.fgColor.rgb.endswith("FFEB9C")
    missing_row = statuses.index("MISSING IN TARGET") + 2
    assert ws.cell(row=missing_row, column=1).fill.fgColor.rgb.endswith("FFC7CE")
    extra_row = statuses.index("EXTRA IN TARGET") + 2
    assert ws.cell(row=extra_row, column=1).fill.fgColor.rgb.endswith("BDD7EE")

    # Header: bold white on dark blue, frozen, with AutoFilter.
    hdr = ws.cell(row=1, column=1)
    assert hdr.font.bold and hdr.fill.fgColor.rgb.endswith("1F4E78")
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:L5"

    # ── Summary: Results table FIRST, trimmed Run Information, three charts ──
    summ = wb["Summary"]
    rows = list(summ.iter_rows(values_only=True))

    # Results table at the very top (task spec).
    assert rows[0][:3] == ("Results", None, None)
    assert rows[1][:3] == ("Category", "Count", "% of Total")
    assert rows[2][:3] == ("Match", 1, "25.0%")
    assert rows[3][:3] == ("Quantity Mismatch", 1, "25.0%")
    assert rows[4][:3] == ("Missing in Target", 1, "25.0%")
    assert rows[5][:3] == ("Extra in Target", 1, "25.0%")
    assert rows[6][:3] == ("Total", 4, "100.0%")
    # Category rows colour-filled by status.
    assert summ.cell(row=3, column=1).fill.fgColor.rgb.endswith("C6EFCE")  # Match: green

    # Run Information trimmed to exactly Run Status / Created At (IST) / Created By.
    flat = {r[0]: r for r in rows if r[0]}
    assert flat["Run Status"][1] == "completed"
    assert flat["Created By"][1] == "system"
    assert flat["Created At"][1].endswith(" IST")
    # Removed metadata must not reappear.
    for removed_label in ("Run ID", "Rules ID", "Rules Version", "Source Snapshot", "Target Snapshot"):
        assert removed_label not in flat
    assert "Exception" not in flat  # exception classification removed

    # Structured "Transformations Applied" table (column E onward) replaces
    # the old per-key-pair "Mapping Review" pie charts — one row per
    # value-mapped business-key field (this fixture has no recipe
    # operations, so both rows are synthesized "value_pairing" entries). All
    # 3 raw source rows survive (no filters): row 0 (Material "A") matches,
    # rows 1/2 ("B"/"C") don't — so both fields (they share the same
    # per-record classification) read 100% applied, 33.3% match, 66.7%
    # mismatch, 0% unresolved.
    ta_rows = [r for r in rows if r[4] == "Transformation"]
    assert ta_rows  # header row present
    by_field = {r[5]: r for r in rows if r[4] == "value_pairing"}
    assert by_field["Material"][6:10] == (100.0, 33.3, 66.7, 0.0)
    assert by_field["Plant"][6:10] == (100.0, 33.3, 66.7, 0.0)

    # One native pie chart: overall results only (the per-key-pair mapping
    # pie charts were replaced by the structured table above).
    assert len(summ._charts) == 1
    titles = [_chart_title(c) for c in summ._charts]
    assert titles == ["Overall Run Results"]

    assert summ.freeze_panes == "A2"


def test_transformations_applied_sheet_lists_both_field_pairs():
    run_id = _completed_run()
    content = service.build_comparison_workbook(run_id)
    wb = openpyxl.load_workbook(BytesIO(content))

    ws = wb["Transformations Applied"]
    rows = list(ws.iter_rows(values_only=True))
    # Just the op-level summary (task spec): no "% Unresolved" column and no
    # per-value drill-down columns/rows.
    assert rows[0] == ("Transformation", "Field(s)", "Rows Applied", "% Applied", "% Match", "% Mismatch")

    # One summary row per value-mapped business-key field (this fixture has
    # no recipe operations) — both Material -> PRDID and Plant -> LOCID
    # appear in the same sheet (task spec: both mappings together, not two
    # separate exports). All 3 raw source rows survive (no filters): row 0
    # (Material "A") matches, rows 1/2 ("B"/"C") don't — so both fields
    # (they share the same per-record classification) read 100% applied,
    # 33.3% match, 66.7% mismatch.
    by_field = {r[1]: r for r in rows[1:] if r[0] == "value_pairing"}
    assert set(by_field) == {"Material", "Plant"}
    assert by_field["Material"][2:6] == (3, 100.0, 33.3, 66.7)
    assert by_field["Plant"][2:6] == (3, 100.0, 33.3, 66.7)

    assert ws.freeze_panes == "A2"


def test_build_comparison_workbook_scales_beyond_two_keys_and_one_compare_field():
    """The whole point of the generalization: a 3rd key pair (Region, beyond
    Material/Plant) and a 2nd compare field must both surface in the export,
    not be silently dropped the way the old fixed 4-role tuple would drop
    them."""
    source_df = pd.DataFrame({
        "Material": ["A"], "Plant": ["P1"], "Region": ["R1"], "Date": ["2024-01-01"],
        "ReqQty": [10], "ReqQty2": [5],
    })
    target_df = pd.DataFrame({
        "PRDID": ["A"], "LOCID": ["P1"], "RegionCode": ["R1"], "Date": ["2024-01-01"],
        "SalesOrderRequest": [10], "SalesOrderRequest2": [5],
    })
    src = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")
    draft, _ = service.compile_draft(
        mapping_sheet=[
            {"source_col": "Material", "target_col": "PRDID", "role": "key"},
            {"source_col": "Plant", "target_col": "LOCID", "role": "key"},
            {"source_col": "Region", "target_col": "RegionCode", "role": "key"},
            {"source_col": "Date", "target_col": "Date", "role": "key"},
            {"source_col": "ReqQty", "target_col": "SalesOrderRequest", "role": "compare"},
            {"source_col": "ReqQty2", "target_col": "SalesOrderRequest2", "role": "compare"},
        ],
        rules="",
        business_key=[
            {"source_field": "Material", "target_field": "PRDID"},
            {"source_field": "Plant", "target_field": "LOCID"},
            {"source_field": "Region", "target_field": "RegionCode"},
            {"source_field": "Date", "target_field": "Date"},
        ],
        compare_fields=[
            {"source_field": "ReqQty", "target_field": "SalesOrderRequest"},
            {"source_field": "ReqQty2", "target_field": "SalesOrderRequest2"},
        ],
        value_mappings=[
            {"source_field": "Material", "target_field": "PRDID", "matches": [
                {"source_value": "A", "target_value": "A", "confidence": "very_high", "rule": "t", "evidence": "e"},
            ]},
            {"source_field": "Plant", "target_field": "LOCID", "matches": [
                {"source_value": "P1", "target_value": "P1", "confidence": "very_high", "rule": "t", "evidence": "e"},
            ]},
            {"source_field": "Region", "target_field": "RegionCode", "matches": [
                {"source_value": "R1", "target_value": "R1", "confidence": "very_high", "rule": "t", "evidence": "e"},
            ]},
        ],
        source_schema=["Material", "Plant", "Region", "Date", "ReqQty", "ReqQty2"],
        target_schema=["PRDID", "LOCID", "RegionCode", "Date", "SalesOrderRequest", "SalesOrderRequest2"],
        comparison_type="c", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )
    contract = service.approve_contract(draft, approved_by="alice")
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src.snapshot_id,
        target_snapshot_id=tgt.snapshot_id,
    )

    content = service.build_comparison_workbook(out["run_id"])
    wb = openpyxl.load_workbook(BytesIO(content))

    ws = wb["All Records"]
    header = next(ws.iter_rows(values_only=True))
    assert header == (
        "Material", "PRDID", "Material Pair ID",
        "Plant", "LOCID", "Plant Pair ID",
        "Region", "RegionCode", "Region Pair ID",
        "Date", "Date",
        "ReqQty", "SalesOrderRequest", "ReqQty → SalesOrderRequest Delta",
        "ReqQty2", "SalesOrderRequest2", "ReqQty2 → SalesOrderRequest2 Delta",
        "Status",
    )
    data_row = next(ws.iter_rows(values_only=True, min_row=2))
    assert data_row[6] == "R1" and data_row[7] == "R1"  # Region / RegionCode
    assert data_row[13] == 0 and data_row[16] == 0  # both compare fields' Delta is 0 (10-10, 5-5)

    # Only the overall-results pie chart remains — the per-key-pair mapping
    # pie charts were replaced by the "Transformations Applied" structured
    # table (Summary sheet, column E onward).
    summ = wb["Summary"]
    assert len(summ._charts) == 1

    mapping_ws = wb["Transformations Applied"]
    # "Field(s)" is column index 1 (0-based) — one summary row per
    # value-mapped business-key field, no per-value drill-down rows.
    labels = {r[1] for r in mapping_ws.iter_rows(values_only=True, min_row=2)}
    assert labels == {"Material", "Plant", "Region"}


def test_all_records_keeps_distinct_values_when_compare_field_shares_a_name():
    """Regression: a compare field named identically on both sides (e.g. both
    "QUANTITY", the common shape for a like-for-like recon) used to have no
    Source/Target disambiguation at all, so writing the Target value into the
    per-row dict silently clobbered the Source value already written under
    the same key — both columns rendered the Target's number even though
    Delta was computed correctly from the real (un-clobbered) values. Source
    and Target must now render their own distinct numbers."""
    source_df = pd.DataFrame({
        "PRDID": ["16613"], "LOCID": ["US01"], "DATE": ["20260105"], "QUANTITY": [3090.311],
    })
    target_df = pd.DataFrame({
        "PRDID": ["16613"], "LOCID": ["US01"], "DATE": ["20260105"], "QUANTITY": [2935.828],
    })
    src = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")
    draft, _ = service.compile_draft(
        mapping_sheet=[
            {"source_col": "PRDID", "target_col": "PRDID", "role": "key"},
            {"source_col": "LOCID", "target_col": "LOCID", "role": "key"},
            {"source_col": "DATE", "target_col": "DATE", "role": "key"},
            {"source_col": "QUANTITY", "target_col": "QUANTITY", "role": "compare"},
        ],
        rules="",
        business_key=[
            {"source_field": "PRDID", "target_field": "PRDID"},
            {"source_field": "LOCID", "target_field": "LOCID"},
            {"source_field": "DATE", "target_field": "DATE"},
        ],
        compare_fields=[{"source_field": "QUANTITY", "target_field": "QUANTITY"}],
        value_mappings=[],
        source_schema=["PRDID", "LOCID", "DATE", "QUANTITY"],
        target_schema=["PRDID", "LOCID", "DATE", "QUANTITY"],
        comparison_type="c", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )
    contract = service.approve_contract(draft, approved_by="alice")
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src.snapshot_id,
        target_snapshot_id=tgt.snapshot_id,
    )

    content = service.build_comparison_workbook(out["run_id"])
    wb = openpyxl.load_workbook(BytesIO(content))
    ws = wb["All Records"]
    rows = list(ws.iter_rows(values_only=True))

    # Every key/compare column headed with the bare field name, never
    # "(Source)"/"(Target)" — and "Status" trails everything.
    assert rows[0] == (
        "PRDID", "PRDID", "LOCID", "LOCID", "DATE", "DATE",
        "QUANTITY", "QUANTITY", "Delta", "Status",
    )
    data = rows[1][:]
    assert data[6] == 3090.311  # Source QUANTITY - the real source value
    assert data[7] == 2935.828  # Target QUANTITY - the real target value, not a copy of Source
    assert data[8] == pytest.approx(154.483, abs=1e-6)  # abs(3090.311 - 2935.828)
    assert data[9] == "QUANTITY MISMATCH"


def test_download_route_returns_xlsx():
    run_id = _completed_run()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    res = client.get(f"/api/recon/runs/{run_id}/comparison.xlsx")
    assert res.status_code == 200, res.text
    assert "spreadsheetml" in res.headers["content-type"]
    assert res.headers["content-disposition"].startswith("attachment")
    assert res.content[:2] == b"PK"  # xlsx is a zip

    missing = client.get("/api/recon/runs/run_does_not_exist/comparison.xlsx")
    assert missing.status_code == 404
