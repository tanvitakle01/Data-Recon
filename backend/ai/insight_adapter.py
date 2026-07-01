"""Presentation-layer adapter for the Enterprise Reconciliation Intelligence Center.

`CockpitAdapter` reshapes InsightEngine's existing analytics (summary, risk,
rootCauses, businessImpacts, recommendations, paretoAnalysis, ...) into the
cockpit payload consumed by the redesigned Insights UI. It adds only a small
set of genuinely new computations (readiness scoring, date-range / mapping-gap
detection, hotspot matrix) and reuses everything else InsightEngine already
computed, so this module never re-derives numbers that already exist in the
engine's output.

The `_MISSING_RE` / `_EXTRA_RE` / `_QTY_MISMATCH_RE` markers mirror the
Remarks contract owned by `ExcelComparator` / `InsightEngine` (✅/⚠️/❌/🔶
prefixed strings) — kept local here rather than imported because InsightEngine
exposes counts, not the underlying boolean masks, and this adapter needs the
row subsets themselves (source-side "missing" rows vs target-side "extra"
rows) to compare value ranges between them.
"""

from __future__ import annotations

import pandas as pd

_MISSING_RE = r"MISSING IN TARGET"
_EXTRA_RE = r"EXTRA IN TARGET"
_QTY_MISMATCH_RE = r"QTY MISMATCH"

_DATE_CANDIDATES = ["deliverydate", "delivery date", "postingdate", "documentdate", "reqdeliverydate", "date"]
_MATERIAL_CANDIDATES = ["material", "matnr", "product", "item", "sku"]
_PLANT_CANDIDATES = ["plant", "werks", "location", "storagelocation"]

_ROOT_CAUSE_TAXONOMY = {
    "Integration Failure": "Quantity Variance",
    "Mapping or Synchronization Issue": "Missing Transactions",
    "Master Data Issue": "Master Data Misalignment",
    "Timing Delay": "Date Range Mismatch",
    "Source Data Quality Issue": "Missing Transactions",
}

_BUSINESS_AREA_TO_RISK_LENS = {
    "Inventory Planning": "Inventory Visibility Risk",
    "Supply Chain": "Fulfillment Risk",
    "Production Planning": "Planning Risk",
    "Procurement": "Planning Risk",
    "Finance": "Reporting Risk",
    "Compliance": "Reporting Risk",
}

_RISK_LENS_ORDER = [
    "Inventory Visibility Risk",
    "Planning Risk",
    "Fulfillment Risk",
    "Reporting Risk",
    "Forecast Accuracy Risk",
]

_PRIORITY_LABELS = {1: "High", 2: "High", 3: "Medium", 4: "Medium", 5: "Low"}


# ----------------------------
# Pure, unit-testable helpers
# ----------------------------
def compute_reconciliation_score(accuracy: float, risk_score: float, readiness_score: float) -> int:
    """Composite headline score — deliberately distinct from accuracy% so the
    hero doesn't just repeat a number shown elsewhere on the page."""
    accuracy = float(accuracy or 0.0)
    risk_score = float(risk_score or 0.0)
    readiness_score = float(readiness_score or 0.0)
    score = accuracy * 0.5 + (100.0 - risk_score) * 0.3 + readiness_score * 0.2
    return int(round(max(0.0, min(100.0, score))))


def classify_system_health(severity: str | None, risk_category: str | None) -> str:
    severity_l = (severity or "").strip().lower()
    risk_l = (risk_category or "").strip().lower()
    if severity_l == "high" or risk_l in ("high", "critical"):
        return "Degraded"
    if severity_l == "medium" or risk_l == "medium":
        return "Attention Needed"
    return "Healthy"


def confidence_label(readiness_score: float) -> str:
    if readiness_score >= 70:
        return "High"
    if readiness_score >= 40:
        return "Medium"
    return "Low"


def map_cause_to_taxonomy(internal_cause: str | None) -> str:
    return _ROOT_CAUSE_TAXONOMY.get(internal_cause or "", "Master Data Misalignment")


def map_area_to_risk_lens(area: str | None) -> str:
    return _BUSINESS_AREA_TO_RISK_LENS.get(area or "", "Forecast Accuracy Risk")


def readiness_status_for(overlap_pct: float, fail_below: float = 40.0, pass_above: float = 70.0) -> str:
    if overlap_pct >= pass_above:
        return "Pass"
    if overlap_pct >= fail_below:
        return "Partial"
    return "Fail"


def compute_readiness_score(factors: list[dict]) -> dict:
    """Pure scoring function: derives a trust score purely from factor
    statuses/weights, so it can be unit tested without a DataFrame fixture.

    factors: [{"name": str, "status": "Pass"|"Partial"|"Fail", "weight": float, "detail": str}]
    """
    if not factors:
        return {"score": 100, "reason": "No readiness signals were available for this dataset.", "factors": []}

    status_score = {"Pass": 1.0, "Partial": 0.5, "Fail": 0.0}
    total_weight = sum(float(f.get("weight", 1.0)) for f in factors) or 1.0
    weighted = sum(status_score.get(f.get("status", "Fail"), 0.0) * float(f.get("weight", 1.0)) for f in factors)
    score = int(round((weighted / total_weight) * 100.0))

    failing = [f["name"] for f in factors if f.get("status") == "Fail"]
    partial = [f["name"] for f in factors if f.get("status") == "Partial"]
    if failing:
        reason = f"{', '.join(failing)} indicate the datasets may not be directly comparable."
    elif partial:
        reason = f"{', '.join(partial)} show partial overlap; treat results with moderate caution."
    else:
        reason = "Datasets show strong overlap and mapping coverage; the reconciliation result is trustworthy."

    return {"score": score, "reason": reason, "factors": factors}


def generate_executive_narrative(
    missing_count: int,
    extra_count: int,
    qty_count: int,
    top_cause_labels: list[str] | None = None,
    readiness_low: bool = False,
) -> str:
    """Pure narrative generator — single read-first paragraph for the hero."""
    missing_count = int(missing_count or 0)
    extra_count = int(extra_count or 0)
    qty_count = int(qty_count or 0)
    total = missing_count + extra_count + qty_count

    if total <= 0:
        return "No reconciliation exceptions were detected; source and target datasets are fully aligned for the analyzed scope."

    lead_bits = []
    if missing_count > 0:
        lead_bits.append(f"{missing_count} records are missing in target systems")
    if extra_count > 0:
        lead_bits.append(f"{extra_count} additional records exist only in target")
    if not lead_bits and qty_count > 0:
        lead_bits.append(f"{qty_count} records show quantity mismatches between source and target")

    lead = (" and ".join(lead_bits) + ".") if lead_bits else f"{total} exceptions were identified."

    causes = [c for c in (top_cause_labels or []) if c][:2]
    if causes:
        causes_text = " and ".join(causes).lower()
        if readiness_low:
            cause_sentence = f" No direct matches were identified due to {causes_text} between source and target systems."
        else:
            cause_sentence = f" Analysis indicates the primary driver is {causes_text}."
    else:
        cause_sentence = ""

    return (lead + cause_sentence).strip()


class CockpitAdapter:
    """Builds the `cockpit` section of the insights payload from InsightEngine's
    already-computed analytics plus a small set of new detections."""

    def __init__(self, engine):
        self._engine = engine

    # ----------------------------
    # Public entrypoint
    # ----------------------------
    def build(self, payload: dict, df: pd.DataFrame, mismatches: pd.DataFrame, type_counts: dict) -> dict:
        missing_df, extra_df, _qty_df = self._split_by_category(mismatches)
        detections = self._detect_taxonomy_causes(missing_df, extra_df)
        readiness = self._build_readiness(payload, detections)

        root_cause_explorer = self._build_root_cause_explorer(payload, detections)

        return {
            "situationRoom": self._build_situation_room(payload, readiness, detections, type_counts),
            "exceptionLandscape": self._build_exception_landscape(payload, type_counts),
            "rootCauseExplorer": root_cause_explorer,
            "hotspots": self._build_hotspots(mismatches, payload),
            "businessImpact": self._build_business_impact(payload),
            "actionCenter": self._build_action_center(payload, root_cause_explorer),
        }

    # ----------------------------
    # Shared row-subset helper
    # ----------------------------
    def _split_by_category(self, mismatches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        if mismatches is None or mismatches.empty or "Remarks" not in mismatches.columns:
            empty = mismatches.iloc[0:0] if mismatches is not None else pd.DataFrame()
            return empty, empty, empty

        remarks = mismatches["Remarks"].fillna("").astype(str)
        missing_mask = remarks.str.contains(_MISSING_RE, case=False, na=False, regex=True)
        extra_mask = remarks.str.contains(_EXTRA_RE, case=False, na=False, regex=True)
        qty_mask = remarks.str.contains(_QTY_MISMATCH_RE, case=False, na=False, regex=True)
        return mismatches.loc[missing_mask], mismatches.loc[extra_mask], mismatches.loc[qty_mask]

    # ----------------------------
    # Root cause taxonomy detections
    # ----------------------------
    def _detect_taxonomy_causes(self, missing_df: pd.DataFrame, extra_df: pd.DataFrame) -> dict:
        return {
            "dateRangeMismatch": self._detect_date_range_mismatch(missing_df, extra_df),
            "productMappingGap": self._detect_mapping_gap(missing_df, extra_df, _MATERIAL_CANDIDATES),
            "locationMappingGap": self._detect_mapping_gap(missing_df, extra_df, _PLANT_CANDIDATES),
        }

    def _detect_date_range_mismatch(self, missing_df: pd.DataFrame, extra_df: pd.DataFrame) -> dict | None:
        date_col = self._engine._detect_column(missing_df, _DATE_CANDIDATES) or self._engine._detect_column(extra_df, _DATE_CANDIDATES)
        if not date_col:
            return None

        missing_dates = pd.to_datetime(missing_df[date_col], errors="coerce").dropna() if date_col in missing_df.columns else pd.Series(dtype="datetime64[ns]")
        extra_dates = pd.to_datetime(extra_df[date_col], errors="coerce").dropna() if date_col in extra_df.columns else pd.Series(dtype="datetime64[ns]")

        if missing_dates.empty or extra_dates.empty:
            return None

        m_start, m_end = missing_dates.min(), missing_dates.max()
        e_start, e_end = extra_dates.min(), extra_dates.max()

        overlap_start = max(m_start, e_start)
        overlap_end = min(m_end, e_end)
        overlap_days = max(0, (overlap_end - overlap_start).days) if overlap_end >= overlap_start else 0

        span_days = max(1, (max(m_end, e_end) - min(m_start, e_start)).days)
        overlap_pct = round(overlap_days / span_days * 100.0, 1)
        confidence = int(round(max(0.0, 100.0 - overlap_pct)))

        return {
            "overlapPct": overlap_pct,
            "confidence": confidence,
            "affectedRecords": int(len(missing_dates) + len(extra_dates)),
            "evidence": (
                f"Source-side records span {m_start.date()}–{m_end.date()}; "
                f"target-only records span {e_start.date()}–{e_end.date()} "
                f"({overlap_pct}% date-range overlap)."
            ),
        }

    def _detect_mapping_gap(self, missing_df: pd.DataFrame, extra_df: pd.DataFrame, candidates: list[str]) -> dict | None:
        col = self._engine._detect_column(missing_df, candidates) or self._engine._detect_column(extra_df, candidates)
        if not col:
            return None

        missing_vals = set(missing_df[col].dropna().astype(str)) if col in missing_df.columns else set()
        extra_vals = set(extra_df[col].dropna().astype(str)) if col in extra_df.columns else set()

        if not missing_vals or not extra_vals:
            return None

        union = missing_vals | extra_vals
        intersection = missing_vals & extra_vals
        overlap_pct = round(len(intersection) / max(1, len(union)) * 100.0, 1)
        confidence = int(round(max(0.0, 100.0 - overlap_pct)))

        return {
            "overlapPct": overlap_pct,
            "confidence": confidence,
            "affectedRecords": int(len(missing_df) + len(extra_df)),
            "evidence": (
                f"Only {len(intersection)} of {len(union)} distinct values are shared between "
                f"source-only and target-only records ({overlap_pct}% overlap)."
            ),
        }

    # ----------------------------
    # Readiness
    # ----------------------------
    def _build_readiness(self, payload: dict, detections: dict) -> dict:
        summary = payload.get("summary") or {}
        total = int(summary.get("totalRecords", 0) or 0)
        matched = int(summary.get("matchedRecords", 0) or 0)
        key_overlap_pct = round(matched / total * 100.0, 1) if total else 0.0

        factors = [{
            "name": "Record Key Overlap",
            "status": readiness_status_for(key_overlap_pct),
            "weight": 1.5,
            "detail": f"{key_overlap_pct}% of records matched by key between source and target.",
        }]

        date_detection = detections.get("dateRangeMismatch")
        if date_detection is not None:
            factors.append({
                "name": "Date Range Overlap",
                "status": readiness_status_for(date_detection["overlapPct"]),
                "weight": 1.5,
                "detail": date_detection["evidence"],
            })

        product_detection = detections.get("productMappingGap")
        if product_detection is not None:
            factors.append({
                "name": "Material Mapping Coverage",
                "status": readiness_status_for(product_detection["overlapPct"]),
                "weight": 1.0,
                "detail": product_detection["evidence"],
            })

        location_detection = detections.get("locationMappingGap")
        if location_detection is not None:
            factors.append({
                "name": "Plant/Location Mapping Coverage",
                "status": readiness_status_for(location_detection["overlapPct"]),
                "weight": 1.0,
                "detail": location_detection["evidence"],
            })

        return compute_readiness_score(factors)

    # ----------------------------
    # Situation Room
    # ----------------------------
    def _build_situation_room(self, payload: dict, readiness: dict, detections: dict, type_counts: dict) -> dict:
        summary = payload.get("summary") or {}
        risk = payload.get("risk") or {}

        accuracy = float(summary.get("accuracy", 0.0) or 0.0)
        risk_score = float(risk.get("score", 0) or 0)
        readiness_score = float(readiness.get("score", 0) or 0)

        recon_score = compute_reconciliation_score(accuracy, risk_score, readiness_score)
        system_health = classify_system_health(summary.get("severity"), risk.get("category"))

        missing = int(type_counts.get("Missing in Target", 0) or 0)
        extra = int(type_counts.get("Extra in Target", 0) or 0)
        qty = int(type_counts.get("Quantity Mismatch", 0) or 0)

        top_causes = []
        if detections.get("dateRangeMismatch") and detections["dateRangeMismatch"]["confidence"] >= 60:
            top_causes.append("date-range inconsistencies")
        if detections.get("productMappingGap") and detections["productMappingGap"]["confidence"] >= 60:
            top_causes.append("master-data mapping gaps")
        if detections.get("locationMappingGap") and detections["locationMappingGap"]["confidence"] >= 60:
            top_causes.append("location mapping gaps")

        narrative = generate_executive_narrative(
            missing_count=missing,
            extra_count=extra,
            qty_count=qty,
            top_cause_labels=top_causes,
            readiness_low=readiness_score < 50,
        )

        return {
            "reconciliationScore": recon_score,
            "totalExceptions": int(summary.get("mismatchedRecords", 0) or 0),
            "severity": summary.get("severity", "Low"),
            "confidenceLevel": confidence_label(readiness_score),
            "systemHealth": system_health,
            "narrative": narrative,
            "readiness": readiness,
        }

    # ----------------------------
    # Exception Landscape
    # ----------------------------
    def _build_exception_landscape(self, payload: dict, type_counts: dict) -> dict:
        summary = payload.get("summary") or {}
        total = int(summary.get("mismatchedRecords", 0) or 0)
        business_impacts = payload.get("businessImpacts") or []

        def pct(n: int) -> float:
            return round(n / total * 100.0, 1) if total else 0.0

        def contribution(p: float) -> str:
            if p >= 50:
                return "High"
            if p >= 20:
                return "Medium"
            return "Low"

        missing = int(type_counts.get("Missing in Target", 0) or 0)
        extra = int(type_counts.get("Extra in Target", 0) or 0)
        qty = int(type_counts.get("Quantity Mismatch", 0) or 0)

        missing_pct, extra_pct, qty_pct = pct(missing), pct(extra), pct(qty)
        high_severity_areas = sum(1 for b in business_impacts if b.get("severity") == "High")

        return {
            "missing": {"count": missing, "distributionPct": missing_pct, "severityContribution": contribution(missing_pct)},
            "extra": {"count": extra, "distributionPct": extra_pct, "severityContribution": contribution(extra_pct)},
            "qtyMismatch": {"count": qty, "distributionPct": qty_pct, "severityContribution": contribution(qty_pct)},
            "dominantCategory": summary.get("dominantMismatchCategory", "No mismatches"),
            "businessImpactEstimate": {
                "affectedAreas": len(business_impacts),
                "highSeverityAreas": high_severity_areas,
            },
        }

    # ----------------------------
    # Root Cause Explorer
    # ----------------------------
    _TAXONOMY_LABELS = {
        "dateRangeMismatch": "Date Range Mismatch",
        "productMappingGap": "Product Mapping Gap",
        "locationMappingGap": "Location Mapping Gap",
    }

    def _build_root_cause_explorer(self, payload: dict, detections: dict) -> list[dict]:
        total_exceptions = int((payload.get("summary") or {}).get("mismatchedRecords", 0) or 0)
        causes: list[dict] = []

        for key, label in self._TAXONOMY_LABELS.items():
            d = detections.get(key)
            if d and d["confidence"] >= 60:
                causes.append({
                    "cause": label,
                    "confidence": d["confidence"],
                    "impact": "High" if d["confidence"] >= 80 else "Medium",
                    "affectedRecords": d["affectedRecords"],
                    "evidence": d["evidence"],
                })

        for rc in payload.get("rootCauses") or []:
            taxonomy_cause = map_cause_to_taxonomy(rc.get("cause"))
            if any(c["cause"] == taxonomy_cause for c in causes):
                continue
            confidence = int(rc.get("confidence", 60) or 60)
            causes.append({
                "cause": taxonomy_cause,
                "confidence": confidence,
                "impact": "High" if confidence >= 80 else "Medium",
                "affectedRecords": total_exceptions,
                "evidence": rc.get("reason"),
            })

        return sorted(causes, key=lambda c: c["confidence"], reverse=True)[:6]

    # ----------------------------
    # Hotspots
    # ----------------------------
    def _build_hotspots(self, mismatches: pd.DataFrame, payload: dict) -> dict:
        pareto = payload.get("paretoAnalysis") or {}

        return {
            "plants": self._top_from_pareto(pareto.get("plants")),
            "materials": self._top_from_pareto(pareto.get("materials")),
            "dates": self._top_dates(mismatches),
            "matrix": self._build_hotspot_matrix(mismatches),
        }

    @staticmethod
    def _top_from_pareto(bucket: dict | None, limit: int = 10) -> list[dict]:
        if not bucket:
            return []
        return (bucket.get("topContributors") or [])[:limit]

    def _top_dates(self, mismatches: pd.DataFrame, limit: int = 10) -> list[dict]:
        if mismatches is None or mismatches.empty:
            return []
        date_col = self._engine._detect_column(mismatches, _DATE_CANDIDATES)
        if not date_col or date_col not in mismatches.columns:
            return []

        dt = pd.to_datetime(mismatches[date_col], errors="coerce").dropna()
        if dt.empty:
            return []

        total = len(mismatches)
        counts = dt.dt.date.astype(str).value_counts().head(limit)
        return [
            {"date": str(k), "mismatchCount": int(v), "share": round(v / max(1, total) * 100.0, 1)}
            for k, v in counts.items()
        ]

    def _build_hotspot_matrix(self, mismatches: pd.DataFrame, top_n: int = 8) -> dict:
        empty_matrix = {"rowDim": "plant", "colDim": "week", "cells": []}
        if mismatches is None or mismatches.empty:
            return empty_matrix

        plant_col = self._engine._detect_column(mismatches, _PLANT_CANDIDATES)
        date_col = self._engine._detect_column(mismatches, _DATE_CANDIDATES)
        if not plant_col or not date_col or plant_col not in mismatches.columns or date_col not in mismatches.columns:
            return empty_matrix

        work = mismatches[[plant_col, date_col]].copy()
        work["_dt"] = pd.to_datetime(work[date_col], errors="coerce")
        work = work.dropna(subset=["_dt"])
        if work.empty:
            return empty_matrix

        work["_week"] = work["_dt"].dt.to_period("W").astype(str)
        work["_plant"] = work[plant_col].fillna("Unknown").astype(str)

        top_plants = work["_plant"].value_counts().head(top_n).index.tolist()
        work = work[work["_plant"].isin(top_plants)]
        if work.empty:
            return empty_matrix

        grouped = work.groupby(["_plant", "_week"]).size().reset_index(name="count")
        cells = [{"row": str(r["_plant"]), "col": str(r["_week"]), "value": int(r["count"])} for _, r in grouped.iterrows()]

        return {"rowDim": "plant", "colDim": "week", "cells": cells}

    # ----------------------------
    # Business Impact Center
    # ----------------------------
    def _build_business_impact(self, payload: dict) -> list[dict]:
        impacts = payload.get("businessImpacts") or []
        total_affected = int((payload.get("summary") or {}).get("mismatchedRecords", 0) or 0)
        severity_rank = {"High": 3, "Medium": 2, "Low": 1}

        by_lens: dict[str, dict] = {}
        for impact in impacts:
            lens = map_area_to_risk_lens(impact.get("area"))
            existing = by_lens.get(lens)
            if not existing or severity_rank.get(impact.get("severity"), 0) > severity_rank.get(existing.get("level"), 0):
                by_lens[lens] = {
                    "riskArea": lens,
                    "level": impact.get("severity", "Low"),
                    "affectedRecords": total_affected,
                    "recommendation": impact.get("impact"),
                }

        return [by_lens[lens] for lens in _RISK_LENS_ORDER if lens in by_lens]

    # ----------------------------
    # Action Center
    # ----------------------------
    def _build_action_center(self, payload: dict, root_cause_explorer: list[dict]) -> list[dict]:
        recs = payload.get("recommendations") or []

        def reason_for(title: str | None) -> str | None:
            title_l = (title or "").lower()
            for cause in root_cause_explorer:
                cause_words = cause.get("cause", "").lower().split()
                if any(word in title_l for word in cause_words):
                    return cause.get("evidence") or f"Linked to {cause.get('cause')} (confidence {cause.get('confidence')}%)."
            return None

        actions = []
        for rec in recs:
            priority_num = int(rec.get("priority", 5) or 5)
            impact_level = rec.get("impact", "Medium")
            actions.append({
                "priority": _PRIORITY_LABELS.get(priority_num, "Medium"),
                "title": rec.get("title"),
                "owner": rec.get("owner"),
                "reason": reason_for(rec.get("title")) or f"Prioritized due to {str(impact_level).lower()} impact on reconciliation accuracy.",
                "expectedImpact": rec.get("expectedImprovement"),
            })
        return actions
