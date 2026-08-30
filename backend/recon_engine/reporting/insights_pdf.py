"""Structured PDF export for a run's simple insights payload.

Renders directly from the same shape ``backend.recon_engine.service.
build_simple_insights`` returns (the one ``/insights/from-run-id`` returns and
``SimpleInsightsView.jsx`` consumes): a results breakdown, quantity variance,
per-mapping match rates, and the exception rows. A structured report, not a
screenshot.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_INK = colors.HexColor("#1A1B25")
_MUTED = colors.HexColor("#6B6F80")
_BORDER = colors.HexColor("#E7E8EE")
_HEADER_BG = colors.HexColor("#F4F5F8")

# Same status colours as the Summary sheet / All Records rows in the
# downloadable workbook (backend.recon_engine.service._STATUS_FILL).
_STATUS_TINT = {
    "MATCH": colors.HexColor("#C6EFCE"),
    "QUANTITY MISMATCH": colors.HexColor("#FFEB9C"),
    "MISMATCH": colors.HexColor("#FFC7CE"),
}

# Row cap so a run with tens of thousands of exceptions still produces a
# reasonably sized PDF — the full detail is always available in the
# downloadable comparison workbook.
_MAX_EXCEPTION_ROWS = 200


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], textColor=_INK, spaceAfter=4),
        "subtitle": ParagraphStyle("ReportSubtitle", parent=base["Normal"], textColor=_MUTED, fontSize=10),
        "h2": ParagraphStyle("ReportH2", parent=base["Heading2"], textColor=_INK, spaceBefore=18, spaceAfter=8),
        "body": ParagraphStyle("ReportBody", parent=base["BodyText"], textColor=_INK, leading=15),
        "cell": ParagraphStyle("ReportCell", parent=base["BodyText"], textColor=_INK, fontSize=9, leading=12),
    }


def _table(rows: list[list[Any]], styles: dict, col_widths: list[float] | None = None, row_fills: list[Any] | None = None) -> Table:
    wrapped = [[Paragraph(str(cell) if cell is not None else "", styles["cell"]) for cell in row] for row in rows]
    t = Table(wrapped, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _INK),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]
    if row_fills:
        for idx, fill in enumerate(row_fills, start=1):
            if fill is not None:
                style.append(("BACKGROUND", (0, idx), (-1, idx), fill))
    t.setStyle(TableStyle(style))
    return t


def build_insights_pdf(payload: dict[str, Any], *, run_id: str | None = None) -> bytes:
    """Renders ``payload`` (a :func:`backend.recon_engine.service.
    build_simple_insights` result) into a PDF report, returned as bytes —
    never written to disk, matching this codebase's in-memory-store
    convention for generated files (see reconcile.py's ``_FILE_STORE``)."""
    styles = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        title=f"Reconciliation Insights{f' — {run_id}' if run_id else ''}",
    )
    story: list[Any] = []

    story.append(Paragraph("Reconciliation Insights Report", styles["title"]))
    if run_id:
        story.append(Paragraph(f"Run ID: {run_id}", styles["subtitle"]))
    story.append(Spacer(1, 12))

    # ── Results breakdown ────────────────────────────────────────────────
    results = payload.get("results") or []
    if results:
        story.append(Paragraph("Results", styles["h2"]))
        rows = [["Category", "Count", "% of Total"]]
        fills = [None]
        for r in results:
            rows.append([r.get("label", ""), r.get("count", 0), f"{r.get('pct', 0)}%"])
            fills.append(_STATUS_TINT.get(r.get("status")))
        total = payload.get("total", 0)
        rows.append(["Total", total, "100.0%" if total else "0.0%"])
        fills.append(None)
        story.append(_table(rows, styles, col_widths=[2.5 * inch, 1.5 * inch, 1.5 * inch], row_fills=fills))

    # ── Quantity variance ────────────────────────────────────────────────
    variance = payload.get("quantityVariance")
    if isinstance(variance, dict):
        story.append(Paragraph("Quantity Variance", styles["h2"]))
        story.append(
            Paragraph(
                f"<b>{variance.get('totalUnits', 0)}</b> total units of variance across "
                f"<b>{variance.get('fieldsAffected', 0)}</b> field(s) — largest single delta: "
                f"<b>{variance.get('largestUnit', 0)}</b> units.",
                styles["body"],
            )
        )

    # ── Per-mapping match rates ──────────────────────────────────────────
    mappings = payload.get("mappings") or []
    if mappings:
        story.append(Paragraph("Mapping Match Rates", styles["h2"]))
        rows = [["Mapping", "Matched", "Unmatched"]]
        for m in mappings:
            rows.append([m.get("label", ""), m.get("matched", 0), m.get("unmatched", 0)])
        story.append(_table(rows, styles, col_widths=[3 * inch, 1.5 * inch, 1.5 * inch]))

    # ── Exception rows ───────────────────────────────────────────────────
    exceptions = payload.get("exceptions") or {}
    columns = exceptions.get("columns") or []
    exc_rows = exceptions.get("rows") or []
    if columns and exc_rows:
        story.append(Paragraph("Exceptions", styles["h2"]))
        if len(exc_rows) > _MAX_EXCEPTION_ROWS:
            story.append(
                Paragraph(
                    f"Showing the first {_MAX_EXCEPTION_ROWS} of {len(exc_rows)} exception rows — "
                    "download the full comparison workbook for the complete list.",
                    styles["subtitle"],
                )
            )
        rows = [columns]
        for rec in exc_rows[:_MAX_EXCEPTION_ROWS]:
            rows.append([rec.get(c) for c in columns])
        col_width = min(1.6 * inch, (LETTER[0] - 1.5 * inch) / max(1, len(columns)))
        story.append(_table(rows, styles, col_widths=[col_width] * len(columns)))
    elif not (results or variance or mappings):
        story.append(Paragraph("No reconciliation exceptions to report — everything matched.", styles["body"]))

    doc.build(story)
    return buf.getvalue()
