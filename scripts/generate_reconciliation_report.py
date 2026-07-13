"""Generate a 2-sheet reconciliation report workbook (.xlsx).

Sheet 1 — "Reconciliation Summary": a compact dashboard of run/contract/snapshot
metadata plus colour-coded classification counters.
Sheet 2 — "Detailed Reconciliation Records": every exception/difference row,
sorted issues-first, with row-level colour coding, frozen header and autofilter.

Field names mirror backend.recon_engine.models (ReconciliationRun,
ReconciliationSummary, RawSnapshot, TransformationContract).

Usage:
    venv/Scripts/python.exe scripts/generate_reconciliation_report.py [output.xlsx]
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

# --------------------------------------------------------------------------- #
# Palette (business-dashboard friendly)
# --------------------------------------------------------------------------- #
NAVY = "1F3864"          # section header background
WHITE = "FFFFFF"
LIGHT_GREY = "F2F2F2"     # label column background
BORDER_GREY = "D9D9D9"

# Metric accent fills (solid, for the summary value chips)
FILL_GREEN = "C6EFCE"     # Match
FILL_GREEN_TXT = "006100"
FILL_ORANGE = "FFE4B5"    # Quantity Mismatch
FILL_ORANGE_TXT = "9C5700"
FILL_RED = "FFC7CE"       # Missing in Source / Target
FILL_RED_TXT = "9C0006"
FILL_GRAY = "D9D9D9"      # Exception
FILL_GRAY_TXT = "3F3F3F"
FILL_BLUE = "DDEBF7"      # neutral / total
FILL_BLUE_TXT = "1F3864"

# Row-level fills for the detail sheet
ROW_RED = "FDE6E6"        # Missing records (light red)
ROW_ORANGE = "FFF1DB"     # Quantity mismatch (light orange)
ROW_YELLOW = "FFFBE0"     # Extra in target (light yellow)
ROW_GREEN = "E6F4EA"      # Match (light green)

THIN = Side(style="thin", color=BORDER_GREY)
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# --------------------------------------------------------------------------- #
# Sample reconciliation payload (shape matches recon_engine models).
# Replace this dict with real data pulled from the run/result/snapshot stores.
# --------------------------------------------------------------------------- #
def _fmt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


RUN = {
    "run_id": "run_9f4c2a1e8b7d",
    "status": "completed",
    "created_at": datetime(2026, 7, 10, 8, 14, 3, tzinfo=timezone.utc),
    "created_by": "tanvi.takle@bristlecone.com",
    "contract_id": "contract_salesorderhistory_v",
    "contract_version": 3,
    "compiler": "groq",
    "approved_by": "supply.planner@bristlecone.com",
    "approved_at": datetime(2026, 7, 9, 16, 42, 0, tzinfo=timezone.utc),
}

SOURCE_SNAPSHOT = {
    "snapshot_id": "snap_src_5a2b9c",
    "layer": "Raw_Source",
    "source_type": "s4",
    "row_count": 1284,
    "snapshot_hash": "3f9a1c...e82d",
    "created_at": datetime(2026, 7, 10, 8, 12, 55, tzinfo=timezone.utc),
}

TARGET_SNAPSHOT = {
    "snapshot_id": "snap_tgt_7d3e0f",
    "layer": "Raw_Target",
    "source_type": "ibp",
    "row_count": 1301,
    "snapshot_hash": "b71e44...09aa",
    "created_at": datetime(2026, 7, 10, 8, 13, 20, tzinfo=timezone.utc),
}

SUMMARY = {
    "match": 1180,
    "mismatch": 47,        # quantity mismatch
    "missing_in_source": 34,
    "missing_in_target": 51,
    "exception": 9,
}
SUMMARY["total"] = sum(SUMMARY.values())

# Detail rows: (Location, Product, Quantity, Date, Status, Reconciliation Key)
STATUS_MISSING_TARGET = "❌ MISSING IN TARGET"
STATUS_MISSING_SOURCE = "❌ MISSING IN SOURCE"
STATUS_QTY_MISMATCH = "⚠️ QUANTITY MISMATCH"
STATUS_EXTRA_TARGET = "🔶 EXTRA IN TARGET"
STATUS_MATCH = "✅ MATCH"

DETAIL_ROWS = [
    ("Plant_1000", "FG-1001", 520, "2026-07-01", STATUS_MISSING_TARGET, "Plant_1000|FG-1001|2026-07-01"),
    ("Plant_1000", "FG-1044", 340, "2026-07-03", STATUS_MISSING_TARGET, "Plant_1000|FG-1044|2026-07-03"),
    ("Plant_2000", "FG-2210", 128, "2026-07-05", STATUS_MISSING_TARGET, "Plant_2000|FG-2210|2026-07-05"),
    ("Plant_3000", "RM-8801", 960, "2026-07-02", STATUS_MISSING_SOURCE, "Plant_3000|RM-8801|2026-07-02"),
    ("Plant_3000", "RM-8802", 145, "2026-07-04", STATUS_MISSING_SOURCE, "Plant_3000|RM-8802|2026-07-04"),
    ("Plant_1000", "FG-1002", 610, "2026-07-01", STATUS_QTY_MISMATCH, "Plant_1000|FG-1002|2026-07-01"),
    ("Plant_2000", "FG-2001", 275, "2026-07-06", STATUS_QTY_MISMATCH, "Plant_2000|FG-2001|2026-07-06"),
    ("Plant_2000", "FG-2205", 88, "2026-07-07", STATUS_QTY_MISMATCH, "Plant_2000|FG-2205|2026-07-07"),
    ("Plant_4000", "FG-4410", 12, "2026-07-08", STATUS_EXTRA_TARGET, "Plant_4000|FG-4410|2026-07-08"),
    ("Plant_4000", "FG-4411", 30, "2026-07-08", STATUS_EXTRA_TARGET, "Plant_4000|FG-4411|2026-07-08"),
    ("Plant_1000", "FG-1001", 500, "2026-07-02", STATUS_MATCH, "Plant_1000|FG-1001|2026-07-02"),
    ("Plant_1000", "FG-1010", 420, "2026-07-02", STATUS_MATCH, "Plant_1000|FG-1010|2026-07-02"),
    ("Plant_2000", "FG-2001", 275, "2026-07-05", STATUS_MATCH, "Plant_2000|FG-2001|2026-07-05"),
    ("Plant_3000", "RM-8801", 960, "2026-07-03", STATUS_MATCH, "Plant_3000|RM-8801|2026-07-03"),
]

# Issues-first sort order.
STATUS_ORDER = {
    STATUS_MISSING_TARGET: 0,
    STATUS_MISSING_SOURCE: 1,
    STATUS_QTY_MISMATCH: 2,
    STATUS_EXTRA_TARGET: 3,
    STATUS_MATCH: 4,
}

ROW_FILL_BY_STATUS = {
    STATUS_MISSING_TARGET: ROW_RED,
    STATUS_MISSING_SOURCE: ROW_RED,
    STATUS_QTY_MISMATCH: ROW_ORANGE,
    STATUS_EXTRA_TARGET: ROW_YELLOW,
    STATUS_MATCH: ROW_GREEN,
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _autosize(ws: Worksheet, min_width: int = 10, max_width: int = 60) -> None:
    widths: dict[int, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            length = max(len(line) for line in str(cell.value).splitlines()) if str(cell.value) else 0
            widths[cell.column] = max(widths.get(cell.column, 0), length)
    for col_idx, width in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = min(
            max(width + 3, min_width), max_width
        )


def _section_header(ws: Worksheet, row: int, text: str, span: int = 2) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = Font(bold=True, color=WHITE, size=11)
    cell.fill = PatternFill("solid", fgColor=NAVY)
    cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[row].height = 22
    for col in range(1, span + 1):
        ws.cell(row=row, column=col).border = BORDER
    return row + 1


def _kv(ws: Worksheet, row: int, label: str, value, *, value_fill=None, value_txt=None, bold_value=False) -> int:
    lc = ws.cell(row=row, column=1, value=label)
    lc.font = Font(bold=True, color="3F3F3F")
    lc.fill = PatternFill("solid", fgColor=LIGHT_GREY)
    lc.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    lc.border = BORDER

    vc = ws.cell(row=row, column=2, value=value)
    vc.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    vc.border = BORDER
    font_kwargs = {"bold": bold_value}
    if value_txt:
        font_kwargs["color"] = value_txt
    vc.font = Font(**font_kwargs)
    if value_fill:
        vc.fill = PatternFill("solid", fgColor=value_fill)
    return row + 1


# --------------------------------------------------------------------------- #
# Sheet 1 — Reconciliation Summary
# --------------------------------------------------------------------------- #
def build_summary_sheet(wb: Workbook) -> None:
    ws = wb.active
    ws.title = "Reconciliation Summary"
    ws.sheet_view.showGridLines = False

    # Title banner
    ws.merge_cells("A1:B1")
    title = ws.cell(row=1, column=1, value="RECONCILIATION SUMMARY")
    title.font = Font(bold=True, size=16, color=WHITE)
    title.fill = PatternFill("solid", fgColor=NAVY)
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    r = 3

    # Run details
    r = _section_header(ws, r, "Run Details")
    status_val = RUN["status"].capitalize()
    status_fill = FILL_GREEN if RUN["status"].lower() == "completed" else None
    status_txt = FILL_GREEN_TXT if RUN["status"].lower() == "completed" else None
    r = _kv(ws, r, "Run ID", RUN["run_id"])
    r = _kv(ws, r, "Status", status_val, value_fill=status_fill, value_txt=status_txt, bold_value=True)
    r = _kv(ws, r, "Created At", _fmt(RUN["created_at"]))
    r = _kv(ws, r, "Created By", RUN["created_by"])
    r += 1

    # Contract details
    r = _section_header(ws, r, "Contract Details")
    r = _kv(ws, r, "Contract ID", RUN["contract_id"])
    r = _kv(ws, r, "Contract Version", f"v{RUN['contract_version']}")
    r = _kv(ws, r, "Compiler", RUN["compiler"])
    r = _kv(ws, r, "Approved By", RUN["approved_by"] or "—")
    r = _kv(ws, r, "Approved At", _fmt(RUN["approved_at"]))
    r += 1

    # Source snapshot
    r = _section_header(ws, r, "Source Snapshot")
    s = SOURCE_SNAPSHOT
    r = _kv(ws, r, "Snapshot ID", s["snapshot_id"])
    r = _kv(ws, r, "Layer", s["layer"])
    r = _kv(ws, r, "Source Type", str(s["source_type"]).upper())
    r = _kv(ws, r, "Row Count", f"{s['row_count']:,}")
    r = _kv(ws, r, "Snapshot Hash", s["snapshot_hash"])
    r = _kv(ws, r, "Captured At", _fmt(s["created_at"]))
    r += 1

    # Target snapshot
    r = _section_header(ws, r, "Target Snapshot")
    t = TARGET_SNAPSHOT
    r = _kv(ws, r, "Snapshot ID", t["snapshot_id"])
    r = _kv(ws, r, "Layer", t["layer"])
    r = _kv(ws, r, "Source Type", str(t["source_type"]).upper())
    r = _kv(ws, r, "Row Count", f"{t['row_count']:,}")
    r = _kv(ws, r, "Snapshot Hash", t["snapshot_hash"])
    r = _kv(ws, r, "Captured At", _fmt(t["created_at"]))
    r += 1

    # Reconciliation metrics (colour-coded)
    r = _section_header(ws, r, "Reconciliation Metrics")
    r = _kv(ws, r, "Match", f"{SUMMARY['match']:,}", value_fill=FILL_GREEN, value_txt=FILL_GREEN_TXT, bold_value=True)
    r = _kv(ws, r, "Quantity Mismatch", f"{SUMMARY['mismatch']:,}", value_fill=FILL_ORANGE, value_txt=FILL_ORANGE_TXT, bold_value=True)
    r = _kv(ws, r, "Missing in Source", f"{SUMMARY['missing_in_source']:,}", value_fill=FILL_RED, value_txt=FILL_RED_TXT, bold_value=True)
    r = _kv(ws, r, "Missing in Target", f"{SUMMARY['missing_in_target']:,}", value_fill=FILL_RED, value_txt=FILL_RED_TXT, bold_value=True)
    r = _kv(ws, r, "Exception", f"{SUMMARY['exception']:,}", value_fill=FILL_GRAY, value_txt=FILL_GRAY_TXT, bold_value=True)
    r = _kv(ws, r, "Total Records", f"{SUMMARY['total']:,}", value_fill=FILL_BLUE, value_txt=FILL_BLUE_TXT, bold_value=True)

    _autosize(ws, min_width=18, max_width=48)
    # Give the value column a comfortable minimum.
    if ws.column_dimensions["B"].width < 34:
        ws.column_dimensions["B"].width = 34


# --------------------------------------------------------------------------- #
# Sheet 2 — Detailed Reconciliation Records
# --------------------------------------------------------------------------- #
def build_detail_sheet(wb: Workbook) -> None:
    ws = wb.create_sheet("Detailed Reconciliation Records")
    ws.sheet_view.showGridLines = False

    headers = ["Location", "Product", "Quantity", "Date", "Status", "Reconciliation Key"]
    header_fill = PatternFill("solid", fgColor=NAVY)
    for col, name in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=name)
        c.font = Font(bold=True, color=WHITE, size=11)
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BORDER
    ws.row_dimensions[1].height = 20

    rows = sorted(DETAIL_ROWS, key=lambda x: (STATUS_ORDER.get(x[4], 99), x[0], x[1]))

    for i, (loc, prod, qty, dt, status, key) in enumerate(rows, start=2):
        fill = PatternFill("solid", fgColor=ROW_FILL_BY_STATUS.get(status, WHITE))
        values = [loc, prod, qty, dt, status, key]
        for col, val in enumerate(values, start=1):
            c = ws.cell(row=i, column=col, value=val)
            c.fill = fill
            c.border = BORDER
            if col == 3:  # Quantity
                c.alignment = Alignment(horizontal="right", vertical="center")
                c.number_format = "#,##0"
            elif col in (4, 5):  # Date, Status
                c.alignment = Alignment(horizontal="center", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center", indent=1)

    last_row = len(rows) + 1
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last_row}"
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=12, max_width=40)


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "Reconciliation_Report.xlsx"
    wb = Workbook()
    build_summary_sheet(wb)
    build_detail_sheet(wb)
    wb.save(out)
    print(f"Wrote {out}  (sheets: {wb.sheetnames})")


if __name__ == "__main__":
    main()
