"""Comparison-sheet export: service.build_comparison_workbook + the route."""

from __future__ import annotations

from io import BytesIO

import openpyxl
import pandas as pd
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
    assert wb.sheetnames == ["Summary", "All Records", "Mapping Details"]

    # ── All Records: column set computed per contract — same 9 columns/content
    # as before, generic names instead of the old fixed Original*/Date labels.
    ws = wb["All Records"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == (
        "Material (Original)", "PRDID (Paired)", "Plant (Original)", "LOCID (Paired)",
        "Date", "Status", "ReqQty", "SalesOrderRequest", "Delta",
        "Run ID", "Batch ID", "Record ID", "Material Pair ID", "Plant Pair ID",
    )

    data = rows[1:]
    statuses = [r[5] for r in data]
    # Dataset -> A match, B quantity mismatch, C missing-in-target and D
    # missing_in_source both collapse onto the single "Mismatch" category.
    # Sort order: quantity mismatch, mismatch (C then D), match.
    assert statuses == ["QUANTITY MISMATCH", "MISMATCH", "MISMATCH", "MATCH"]

    # Two rows now share the "MISMATCH" status, so key off OriginalPRDID
    # (col 1) instead, which is unique across all four rows in this fixture.
    by_prdid = {r[1]: r for r in data}

    # Match (A): raw Material differs from the paired PRDID — both sides
    # visible side by side — Delta is 0 (10 - 10).
    match = by_prdid["PA"]
    assert match[0] == "A" and match[1] == "PA"
    assert match[2] == "P1" and match[3] == "LOC1"
    assert match[6] == 10 and match[7] == 10 and match[8] == 0

    # Quantity Mismatch (B): identity-mapped Material/Plant, Delta signed (20 - 25).
    mm = by_prdid["B"]
    assert mm[0] == "B" and mm[1] == "B"
    assert mm[6] == 20 and mm[7] == 25 and mm[8] == -5

    # Mismatch (C, missing in target/source only): target-side quantity is
    # null, Delta convention treats the absent target side as 0 -> Delta == ReqQty.
    missing = by_prdid["C"]
    assert missing[0] == "C" and missing[1] == "C"
    assert missing[6] == 30 and missing[7] is None and missing[8] == 30

    # Mismatch (D, extra in target/missing in source): source-side quantity is
    # null, no raw source row exists so OriginalMaterial is null but
    # OriginalPRDID falls back to the target's own PRDID value; Delta ==
    # -SalesOrderRequest.
    extra = by_prdid["D"]
    assert extra[0] is None and extra[1] == "D"
    assert extra[6] is None and extra[7] == 40 and extra[8] == -40

    # Traceability columns (see recon_engine.ids): Run ID is always known,
    # even for this Manual-mode run, which has no per-row batch/pair identity
    # of its own — Batch ID/Record ID/Pair ID all stay blank.
    for r in data:
        assert r[9] == run_id
        assert r[10] is None and r[11] is None
        assert r[12] is None and r[13] is None

    # Whole row filled with the status colour (amber for quantity mismatch,
    # red for the unified mismatch bucket).
    qty_row = statuses.index("QUANTITY MISMATCH") + 2  # +1 header, +1 to 1-index
    assert ws.cell(row=qty_row, column=1).fill.fgColor.rgb.endswith("FFEB9C")
    assert ws.cell(row=qty_row, column=9).fill.fgColor.rgb.endswith("FFEB9C")
    mismatch_row = statuses.index("MISMATCH") + 2
    assert ws.cell(row=mismatch_row, column=1).fill.fgColor.rgb.endswith("FFC7CE")

    # Header: bold white on dark blue, frozen, with AutoFilter.
    hdr = ws.cell(row=1, column=1)
    assert hdr.font.bold and hdr.fill.fgColor.rgb.endswith("1F4E78")
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:N5"

    # ── Summary: Results table FIRST, trimmed Run Information, three charts ──
    summ = wb["Summary"]
    rows = list(summ.iter_rows(values_only=True))

    # Results table at the very top (task spec).
    assert rows[0][:3] == ("Results", None, None)
    assert rows[1][:3] == ("Category", "Count", "% of Total")
    assert rows[2][:3] == ("Match", 1, "25.0%")
    assert rows[3][:3] == ("Quantity Mismatch", 1, "25.0%")
    assert rows[4][:3] == ("Mismatch", 2, "50.0%")
    assert rows[5][:3] == ("Total", 4, "100.0%")
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

    # Chart-data mini tables (Material/Plant matched vs. unmatched) — Material
    # A/B/C all resolve (3 matched, 0 unmatched); Plant P1 resolves (1 matched).
    # Column E holds the label ("Material → PRDID Mapping" / "Matched" / ...),
    # column F the count; indices below follow the two 3-row blocks written
    # by build_comparison_workbook (header, Matched, Unmatched) per mapping.
    chart_data_rows = [r for r in rows if r[4] is not None]
    assert chart_data_rows[0][4] == "Material → PRDID Mapping"
    assert chart_data_rows[1][4] == "Matched" and chart_data_rows[1][5] == 3
    assert chart_data_rows[2][4] == "Unmatched" and chart_data_rows[2][5] == 0
    assert chart_data_rows[4][4] == "Matched" and chart_data_rows[4][5] == 1
    assert chart_data_rows[5][4] == "Unmatched" and chart_data_rows[5][5] == 0

    # Three native pie charts: overall results + one per mapped key pair.
    # Titles use the contract's actual field names generically now (no more
    # hardcoded "Product ID"/"Location ID" aliases tied to Material/Plant).
    assert len(summ._charts) == 3
    titles = [_chart_title(c) for c in summ._charts]
    assert titles == [
        "Overall Run Results",
        "Material → PRDID Mapping Review",
        "Plant → LOCID Mapping Review",
    ]

    assert summ.freeze_panes == "A2"


def test_mapping_details_sheet_lists_both_field_pairs():
    run_id = _completed_run()
    content = service.build_comparison_workbook(run_id)
    wb = openpyxl.load_workbook(BytesIO(content))

    ws = wb["Mapping Details"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == (
        "Mapping", "Source Value", "Target Value", "Status", "Confidence",
        "Corroboration", "Also Candidate For", "Row Count", "Reason", "Pair ID",
    )

    data = rows[1:]
    by_source = {(r[0], r[1]): r for r in data}

    # Material -> PRDID: "A" value-mapped (HIGH -> "Verified"), "B"/"C" identity
    # (VERY_HIGH -> "Identity") — all Paired, no siblings so Corroboration blank.
    a = by_source[("Material → PRDID", "A")]
    assert a[2] == "PA" and a[3] == "Paired" and a[4] == "Verified"
    assert a[5] is None and a[6] is None  # no competing candidates
    # This Manual-mode contract's matches carry no pair_id (see
    # recon_engine.ids/models.value_mapping — set only by the Auto-mode
    # streaming wrapper).
    assert a[9] is None

    b = by_source[("Material → PRDID", "B")]
    assert b[2] == "B" and b[3] == "Paired" and b[4] == "Identity"

    c = by_source[("Material → PRDID", "C")]
    assert c[2] == "C" and c[3] == "Paired" and c[4] == "Identity"

    # Plant -> LOCID also present in the SAME sheet (task spec: both mappings
    # together, not two separate exports).
    p1 = by_source[("Plant → LOCID", "P1")]
    assert p1[2] == "LOC1" and p1[3] == "Paired" and p1[4] == "Verified"

    # Paired rows are colour-filled green.
    a_row = next(i for i, r in enumerate(data, start=2) if r[:2] == ("Material → PRDID", "A"))
    assert ws.cell(row=a_row, column=1).fill.fgColor.rgb.endswith("C6EFCE")

    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == f"A1:J{len(data) + 1}"


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
        "Material (Original)", "PRDID (Paired)",
        "Plant (Original)", "LOCID (Paired)",
        "Region (Original)", "RegionCode (Paired)",
        "Date", "Status",
        "ReqQty", "SalesOrderRequest", "ReqQty → SalesOrderRequest Delta",
        "ReqQty2", "SalesOrderRequest2", "ReqQty2 → SalesOrderRequest2 Delta",
        "Run ID", "Batch ID", "Record ID",
        "Material Pair ID", "Plant Pair ID", "Region Pair ID",
    )
    data_row = next(ws.iter_rows(values_only=True, min_row=2))
    assert data_row[4] == "R1" and data_row[5] == "R1"  # Region (Original) / RegionCode (Paired)
    assert data_row[10] == 0 and data_row[13] == 0  # both compare fields' Delta is 0 (10-10, 5-5)

    # Overall + 3 mapped key pairs (Material/Plant/Region — Date has no value
    # mapping, so no pie chart for it) = 4 pie charts, not capped at 2.
    summ = wb["Summary"]
    assert len(summ._charts) == 4

    mapping_ws = wb["Mapping Details"]
    labels = {r[0] for r in mapping_ws.iter_rows(values_only=True, min_row=2)}
    assert labels == {"Material → PRDID", "Plant → LOCID", "Region → RegionCode"}


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
