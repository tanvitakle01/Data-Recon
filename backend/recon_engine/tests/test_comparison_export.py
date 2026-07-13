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
    source_df = pd.DataFrame({"Plant": ["A", "B", "C"], "Qty": [10, 20, 30]})
    target_df = pd.DataFrame({"Plant": ["A", "B", "D"], "Qty": [10, 25, 40]})
    src = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")
    draft, _ = service.compile_draft(
        mapping_sheet=[
            {"source_col": "Plant", "target_col": "Plant", "role": "key"},
            {"source_col": "Qty", "target_col": "Qty", "role": "compare"},
        ],
        rules="", source_schema=["Plant", "Qty"], target_schema=["Plant", "Qty"],
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


def test_build_comparison_workbook_is_two_colour_coded_sheets():
    run_id = _completed_run()
    content = service.build_comparison_workbook(run_id)
    wb = openpyxl.load_workbook(BytesIO(content))
    assert wb.sheetnames == ["Summary", "All Records"]

    # ── All Records: one flat, sorted, colour-coded, field-level table ───────
    ws = wb["All Records"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("Plant", "Qty", "_STATUS", "_MISMATCHED_FIELDS")

    data = rows[1:]
    statuses = [r[2] for r in data]
    # Dataset -> A match, B mismatch, C missing-in-target, D missing-in-source.
    # Sort order: mismatch, missing in target, extra in target, match.
    assert statuses == ["MISMATCH", "MISSING IN TARGET", "EXTRA IN TARGET", "MATCH"]

    by_status = {r[2]: r for r in data}
    # Mismatch row: field values shown per-column, plus the mismatched field name.
    mm = by_status["MISMATCH"]
    assert mm[0] == "B" and mm[1] == 20 and mm[3] == "Qty"
    # Missing-in-target: only source side exists, fields still populate.
    assert by_status["MISSING IN TARGET"][0] == "C" and not by_status["MISSING IN TARGET"][3]
    # Extra-in-target (missing_in_source): only target side exists.
    assert by_status["EXTRA IN TARGET"][0] == "D" and not by_status["EXTRA IN TARGET"][3]
    # Match: no mismatched fields.
    assert not by_status["MATCH"][3]

    # Whole row filled with the status colour (amber for mismatch).
    mm_row = statuses.index("MISMATCH") + 2  # +1 header, +1 to 1-index
    assert ws.cell(row=mm_row, column=1).fill.fgColor.rgb.endswith("FFEB9C")
    assert ws.cell(row=mm_row, column=4).fill.fgColor.rgb.endswith("FFEB9C")

    # Header: bold white on dark blue, frozen, with AutoFilter.
    hdr = ws.cell(row=1, column=1)
    assert hdr.font.bold and hdr.fill.fgColor.rgb.endswith("1F4E78")
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:D5"

    # ── Summary: run info + every category (incl. 0-count) + total ───────────
    summ = wb["Summary"]
    flat = {r[0]: r for r in summ.iter_rows(values_only=True) if r[0]}
    assert flat["Run ID"][1] == run_id
    assert flat["Match"][1] == 1
    assert flat["Quantity Mismatch"][1] == 1
    assert flat["Missing in Target"][1] == 1
    assert flat["Missing in Source"][1] == 1
    assert flat["Exception"][1] == 0  # listed even at count 0
    assert flat["Total"][1] == 4
    # % of Total is present and the category row is colour-filled.
    assert flat["Match"][2] == "25.0%"
    match_row = next(i for i, r in enumerate(summ.iter_rows(values_only=True), start=1)
                     if r[0] == "Match")
    assert summ.cell(row=match_row, column=1).fill.fgColor.rgb.endswith("C6EFCE")
    assert summ.freeze_panes == "A2"


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
