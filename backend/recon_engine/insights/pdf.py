"""Structured PDF export of a `facts.build_facts` payload — a printable
report, not a screenshot. Every section is a direct table/number off the
payload; no generated commentary.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_INK = colors.HexColor("#1A1B25")
_MUTED = colors.HexColor("#6B6F80")
_BORDER = colors.HexColor("#E7E8EE")
_HEADER_BG = colors.HexColor("#F4F5F8")

_STATUS_TINT = {
    "match": colors.HexColor("#C6EFCE"),
    "quantity_mismatch": colors.HexColor("#FFEB9C"),
    "missing_in_target": colors.HexColor("#FFC7CE"),
    "missing_in_source": colors.HexColor("#FFC7CE"),
}

_MAX_ROWS_PER_SECTION = 25


def _styles() -> dict[str, ParagraphStyle]:
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
    styles = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        title="Reconciliation Insights",
    )
    story: list[Any] = []

    story.append(Paragraph("Reconciliation Insights Report", styles["title"]))
    if run_id:
        story.append(Paragraph(f"Run ID: {run_id}", styles["subtitle"]))
    story.append(Spacer(1, 12))

    # ── Break-rate summary ───────────────────────────────────────────────
    break_rate = payload.get("breakRate") or {}
    results = break_rate.get("results") or []
    if results:
        story.append(Paragraph("Break-Rate Summary", styles["h2"]))
        rows = [["Category", "Count", "% of Total"]]
        fills = [None]
        for r in results:
            rows.append([r.get("label", ""), r.get("count", 0), f"{r.get('pct', 0)}%"])
            fills.append(_STATUS_TINT.get(r.get("key")))
        total = break_rate.get("total", 0)
        rows.append(["Total", total, "100.0%" if total else "0.0%"])
        fills.append(None)
        story.append(_table(rows, styles, col_widths=[2.5 * inch, 1.5 * inch, 1.5 * inch], row_fills=fills))
        story.append(Spacer(1, 8))
        story.append(
            Paragraph(
                f"Net Delta: <b>{break_rate.get('netDelta', 0)}</b> &nbsp;&nbsp; "
                f"Total Absolute Variance: <b>{break_rate.get('totalAbsoluteVariance', 0)}</b>",
                styles["body"],
            )
        )

    # ── Hotspots ──────────────────────────────────────────────────────────
    for section in payload.get("hotspots") or []:
        section_rows = section.get("rows") or []
        if not section_rows:
            continue
        story.append(Paragraph(f"Hotspots — {section.get('label')}", styles["h2"]))
        rows = [[section.get("label"), "Break Count", "Abs Qty Variance"]]
        for r in section_rows[:_MAX_ROWS_PER_SECTION]:
            rows.append([r.get("value"), r.get("breakCount"), r.get("absQtyVariance")])
        story.append(_table(rows, styles, col_widths=[3 * inch, 1.5 * inch, 1.5 * inch]))

    # ── Variance distribution ────────────────────────────────────────────
    variance_bins = payload.get("varianceDistribution") or []
    if variance_bins:
        story.append(Paragraph("Variance Distribution", styles["h2"]))
        rows = [["Range", "Count", "Total Abs Variance"]]
        for b in variance_bins:
            rows.append([f"{b.get('min')} – {b.get('max')}", b.get("count"), b.get("totalAbsVariance")])
        story.append(_table(rows, styles, col_widths=[3 * inch, 1.5 * inch, 1.5 * inch]))

    # ── Unmapped values by field ──────────────────────────────────────────
    unmapped = payload.get("unmappedByField") or []
    if unmapped:
        story.append(Paragraph("Unmapped Values by Field", styles["h2"]))
        rows = [["Mapping", "Paired", "Unpaired", "Total"]]
        for u in unmapped:
            rows.append([u.get("label"), u.get("paired"), u.get("unpaired"), u.get("total")])
        story.append(_table(rows, styles, col_widths=[3 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch]))

    # ── Date-window coverage ──────────────────────────────────────────────
    coverage = payload.get("dateCoverage")
    if isinstance(coverage, dict):
        story.append(Paragraph("Date-Window Coverage", styles["h2"]))
        story.append(
            Paragraph(
                f"Source: <b>{coverage.get('sourceMin')}</b> to <b>{coverage.get('sourceMax')}</b> — "
                f"Target: <b>{coverage.get('targetMin')}</b> to <b>{coverage.get('targetMax')}</b>. "
                f"{coverage.get('sourceDatesOutsideTargetWindow', 0)} source date(s) fall outside the target's "
                f"covered window; {coverage.get('targetDatesOutsideSourceWindow', 0)} target date(s) fall outside "
                f"the source's covered window.",
                styles["body"],
            )
        )

    if not (results or payload.get("hotspots") or variance_bins or unmapped or coverage):
        story.append(Paragraph("No reconciliation exceptions to report — everything matched.", styles["body"]))

    doc.build(story)
    return buf.getvalue()
