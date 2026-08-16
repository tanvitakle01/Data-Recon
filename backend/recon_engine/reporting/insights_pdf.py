"""Structured PDF export for an Insights payload.

Renders directly from the same top-level payload shape
``backend.ai.insight_engine.InsightEngine.generate`` already produces (the
same one ``/insights/from-run-id`` returns and ``InsightsPage.jsx`` consumes)
— not the richer, UI-shaped ``payload["cockpit"]`` reshape, since these
top-level fields (``kpis``, ``executiveSummary``, ``rootCauses``,
``businessImpacts``, ``recommendations``) are exactly what a clean, printable
report needs: a KPI summary, an executive brief, root causes, business
impact, and recommended actions. A structured report, not a screenshot.
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

_ACCENT = colors.HexColor("#F89F5B")
_INK = colors.HexColor("#1A1B25")
_MUTED = colors.HexColor("#6B6F80")
_BORDER = colors.HexColor("#E7E8EE")
_HEADER_BG = colors.HexColor("#F4F5F8")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], textColor=_INK, spaceAfter=4),
        "subtitle": ParagraphStyle("ReportSubtitle", parent=base["Normal"], textColor=_MUTED, fontSize=10),
        "h2": ParagraphStyle("ReportH2", parent=base["Heading2"], textColor=_INK, spaceBefore=18, spaceAfter=8),
        "body": ParagraphStyle("ReportBody", parent=base["BodyText"], textColor=_INK, leading=15),
        "cell": ParagraphStyle("ReportCell", parent=base["BodyText"], textColor=_INK, fontSize=9, leading=12),
    }


def _table(rows: list[list[Any]], styles: dict, col_widths: list[float] | None = None) -> Table:
    wrapped = [
        [Paragraph(str(cell), styles["cell"]) for cell in row]
        for row in rows
    ]
    t = Table(wrapped, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
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
        )
    )
    return t


def build_insights_pdf(payload: dict[str, Any], *, run_id: str | None = None) -> bytes:
    """Renders ``payload`` (the InsightEngine output) into a PDF report,
    returned as bytes — never written to disk, matching this codebase's
    in-memory-store convention for generated files (see reconcile.py's
    ``_FILE_STORE``)."""
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

    # ── KPI summary ──────────────────────────────────────────────────────
    kpis = payload.get("kpis") or []
    summary = payload.get("summary") or {}
    if summary:
        story.append(Paragraph("Summary", styles["h2"]))
        summary_rows = [["Metric", "Value"]]
        for key in ("total", "matched", "accuracy", "mismatched"):
            if key in summary:
                summary_rows.append([key.replace("_", " ").title(), summary[key]])
        if len(summary_rows) > 1:
            story.append(_table(summary_rows, styles, col_widths=[3 * inch, 3 * inch]))
            story.append(Spacer(1, 8))
    if kpis:
        rows = [["KPI", "Count", "% of total"]]
        for k in kpis:
            rows.append([k.get("title", ""), k.get("value", ""), f"{k.get('percentage', 0)}%"])
        story.append(_table(rows, styles, col_widths=[3 * inch, 1.5 * inch, 1.5 * inch]))

    # ── Executive brief ──────────────────────────────────────────────────
    exec_summary = payload.get("executiveSummary") or {}
    if isinstance(exec_summary, dict) and exec_summary.get("text"):
        story.append(Paragraph("Executive Brief", styles["h2"]))
        story.append(Paragraph(exec_summary["text"], styles["body"]))

    risk = payload.get("risk") or {}
    if isinstance(risk, dict) and risk.get("category"):
        story.append(Spacer(1, 6))
        drivers = ", ".join(risk.get("drivers") or []) or "None identified"
        story.append(
            Paragraph(
                f"<b>Risk score:</b> {risk.get('score', '—')} ({risk.get('category')}) — "
                f"drivers: {drivers}",
                styles["body"],
            )
        )

    # ── Root causes ──────────────────────────────────────────────────────
    root_causes = payload.get("rootCauses") or []
    if root_causes:
        story.append(Paragraph("Top Root Causes", styles["h2"]))
        rows = [["Cause", "Confidence", "Reason"]]
        for c in root_causes:
            rows.append([c.get("cause", ""), f"{c.get('confidence', '—')}%", c.get("reason", "")])
        story.append(_table(rows, styles, col_widths=[1.6 * inch, 0.9 * inch, 3.5 * inch]))

    # ── Business impact ──────────────────────────────────────────────────
    business_impacts = payload.get("businessImpacts") or []
    if business_impacts:
        story.append(Paragraph("Business Impact", styles["h2"]))
        rows = [["Area", "Severity", "Impact"]]
        for b in business_impacts:
            rows.append([b.get("area", ""), b.get("severity", ""), b.get("impact", "")])
        story.append(_table(rows, styles, col_widths=[1.6 * inch, 0.9 * inch, 3.5 * inch]))

    # ── Recommended actions ──────────────────────────────────────────────
    recommendations = payload.get("recommendations") or []
    if recommendations:
        story.append(Paragraph("Recommended Actions", styles["h2"]))
        rows = [["Priority", "Action", "Owner", "Expected Improvement"]]
        for r in sorted(recommendations, key=lambda x: x.get("priority", 99)):
            rows.append(
                [r.get("priority", ""), r.get("title", ""), r.get("owner", ""), r.get("expectedImprovement", "")]
            )
        story.append(_table(rows, styles, col_widths=[0.7 * inch, 2.6 * inch, 1.7 * inch, 1 * inch]))

    if not (kpis or summary or root_causes or business_impacts or recommendations):
        story.append(Paragraph("No reconciliation exceptions to report — everything matched.", styles["body"]))

    doc.build(story)
    return buf.getvalue()
