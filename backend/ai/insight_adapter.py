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

# Recon Score contributor weights (sum to 100) — the score is *literally*
# 100 minus the sum of these weighted penalties, so the breakdown shown in the
# UI is the actual arithmetic behind the number, not an approximation of it.
_RECON_CONTRIBUTOR_WEIGHTS = {
    "Record Mismatches": 40.0,
    "Mapping Failures": 25.0,
    "Quantity Variances": 20.0,
    "Duplicate Records": 15.0,
}

_SEVERITY_WEIGHT = {"High": 1.5, "Medium": 1.0, "Low": 0.5}

# Short, punchy labels for confidence drivers — the verbose `detail` sentence
# stays available for the full explanation, this is just the headline phrase
# used wherever space is tight (executive summary bullet lists).
_DRIVER_SHORT_LABELS = {
    "Record Key Overlap": "Low key overlap",
    "Material Mapping Coverage": "Poor material mapping coverage",
    "Plant/Location Mapping Coverage": "Poor location mapping coverage",
    "Date Range Overlap": "Misaligned date ranges",
    "Exception Concentration": "High exception concentration",
}


def driver_short_label(name: str | None) -> str | None:
    return _DRIVER_SHORT_LABELS.get(name or "")

# Confidence formulas mirrored from InsightEngine._generate_root_causes, kept
# here as prose so root-cause "reasoning" can cite the actual rule without
# re-deriving raw counts the adapter doesn't have at this point.
_ENGINE_CAUSE_FORMULA = {
    "Integration Failure": "Base confidence 70%, plus up to 25 points scaled by the share of exceptions that are quantity mismatches (capped at 95%).",
    "Mapping or Synchronization Issue": "Base confidence 70%, plus up to 25 points scaled by the share of exceptions that are missing-in-target records (capped at 95%).",
    "Master Data Issue": "Base confidence 65%, plus up to 20 points scaled by the share of exceptions that are extra-in-target records (capped at 90%), or a fixed 78% when exceptions concentrate on a small set of materials.",
    "Timing Delay": "Fixed 80% confidence, triggered when a single plant accounts for 35%+ of all exceptions.",
    "Source Data Quality Issue": "Fallback cause at 60% confidence, used when no other pattern (quantity, missing, extra, concentration) dominates.",
}


# ----------------------------
# Pure, unit-testable helpers
# ----------------------------
def severity_contribution(share_pct: float) -> str:
    """Shared High/Medium/Low tiering by share-of-total, used for both
    exception-landscape severity and hotspot risk tiering."""
    share_pct = float(share_pct or 0.0)
    if share_pct >= 50:
        return "High"
    if share_pct >= 20:
        return "Medium"
    return "Low"


def compute_reconciliation_score_breakdown(
    total_records: int,
    record_mismatches: int,
    mapping_failures: int,
    quantity_variances: int,
    duplicate_records: int,
) -> dict:
    """Recon Score as a direct sum of weighted category penalties. Each
    category's penalty is its weight scaled by how much of the dataset it
    affects, capped at the category's full weight — so `contributors` is the
    exact arithmetic behind `score`, auditable line by line."""
    total_records = int(total_records or 0)

    counts = {
        "Record Mismatches": max(0, int(record_mismatches or 0)),
        "Mapping Failures": max(0, int(mapping_failures or 0)),
        "Quantity Variances": max(0, int(quantity_variances or 0)),
        "Duplicate Records": max(0, int(duplicate_records or 0)),
    }

    contributors: list[dict] = []
    penalties: dict[str, float] = {}
    for name, weight in _RECON_CONTRIBUTOR_WEIGHTS.items():
        count = counts[name]
        share_pct = round(count / total_records * 100.0, 1) if total_records else 0.0
        penalty = weight * min(1.0, count / total_records) if total_records else 0.0
        penalties[name] = penalty
        contributors.append({
            "name": name,
            "count": count,
            "sharePct": share_pct,
            "weight": weight,
            "penaltyPoints": round(penalty, 2),
        })

    total_penalty = sum(penalties.values())
    score = int(round(max(0.0, min(100.0, 100.0 - total_penalty))))

    for c in contributors:
        contribution_pct = round(penalties[c["name"]] / total_penalty * 100.0, 1) if total_penalty > 0 else 0.0
        c["contributionPct"] = contribution_pct
        c["impact"] = "High" if contribution_pct >= 50 else ("Medium" if contribution_pct >= 20 else "Low")

    contributors.sort(key=lambda c: c["penaltyPoints"], reverse=True)

    formula = (
        "Score = 100 − Σ(category weight × affected-record share). "
        "Weights: Record Mismatches 40, Mapping Failures 25, Quantity Variances 20, Duplicate Records 15."
    )

    return {"score": score, "contributors": contributors, "formula": formula}


def detect_duplicate_records(df: pd.DataFrame) -> int:
    """Counts full-row duplicates (identical across every column except
    Remarks) in the reconciled dataset — the only duplicate signal available
    without depending on the original key-mapping config."""
    if df is None or df.empty:
        return 0
    subset = [c for c in df.columns if c != "Remarks"]
    if not subset:
        return 0
    return int(df.duplicated(subset=subset, keep=False).sum())


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


_READINESS_FORMULA = "Score = Σ(status score × weight) / Σ(weight) × 100"


def compute_readiness_score(factors: list[dict]) -> dict:
    """Pure scoring function: derives a trust score purely from factor
    statuses/weights, so it can be unit tested without a DataFrame fixture.

    factors: [{"name": str, "status": "Pass"|"Partial"|"Fail", "weight": float, "detail": str}]

    Each returned factor is enriched with `statusScore` (1.0/0.5/0.0),
    `weightPct` (its share of total weight) and `contributionPoints`
    (statusScore × weightPct) — the per-factor arithmetic that sums to
    `score`, so the UI can show the weighted calculation rather than just
    Pass/Partial/Fail pills.
    """
    if not factors:
        return {
            "score": 100,
            "reason": "No readiness signals were available for this dataset.",
            "factors": [],
            "formula": _READINESS_FORMULA,
        }

    status_score = {"Pass": 1.0, "Partial": 0.5, "Fail": 0.0}
    total_weight = sum(float(f.get("weight", 1.0)) for f in factors) or 1.0

    enriched_factors: list[dict] = []
    weighted = 0.0
    for f in factors:
        weight = float(f.get("weight", 1.0))
        s_score = status_score.get(f.get("status", "Fail"), 0.0)
        weight_pct = round(weight / total_weight * 100.0, 1)
        weighted += s_score * weight
        enriched_factors.append({
            **f,
            "statusScore": s_score,
            "weightPct": weight_pct,
            "contributionPoints": round(s_score * weight_pct, 1),
        })

    score = int(round((weighted / total_weight) * 100.0))

    failing = [f["name"] for f in factors if f.get("status") == "Fail"]
    partial = [f["name"] for f in factors if f.get("status") == "Partial"]
    if failing:
        reason = f"{', '.join(failing)} indicate the datasets may not be directly comparable."
    elif partial:
        reason = f"{', '.join(partial)} show partial overlap; treat results with moderate caution."
    else:
        reason = "Datasets show strong overlap and mapping coverage; the reconciliation result is trustworthy."

    return {"score": score, "reason": reason, "factors": enriched_factors, "formula": _READINESS_FORMULA}


def generate_executive_brief(
    total_exceptions: int,
    top_cause_labels: list[str] | None = None,
    readiness_score: float = 100.0,
) -> str:
    """Pure, longer-form management summary (email/reporting), distinct from
    the shorter hero narrative — this one always names the readiness caveat
    explicitly rather than folding it into a single lead sentence."""
    total_exceptions = int(total_exceptions or 0)
    if total_exceptions <= 0:
        return "The current reconciliation cycle identified no exceptions; source and target systems are fully aligned for the analyzed scope."

    lead = f"The current reconciliation identified {total_exceptions} exceptions."

    causes = [c for c in (top_cause_labels or []) if c][:2]
    cause_sentence = f" Analysis indicates the primary cause is {', '.join(causes).lower()}." if causes else ""

    caveat_sentence = ""
    if readiness_score < 50:
        caveat_sentence = (
            " Direct record-level comparison is therefore not fully representative of operational "
            "performance; master-data harmonization and aligned date filtering are recommended before "
            "further reconciliation activities."
        )

    return (lead + cause_sentence + caveat_sentence).strip()


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


def _readiness_band(score: float) -> str:
    if score >= 70:
        return "strong"
    if score >= 40:
        return "moderate"
    return "low"


def generate_executive_brief_bullets(
    total_exceptions: int,
    root_causes: list[dict] | None,
    score_breakdown: dict | None,
    readiness: dict | None,
) -> list[str]:
    """Deterministic, Python-only bulleted executive brief — no LLM. Every
    statement is read directly off numbers `CockpitAdapter.build()` has
    already computed elsewhere (root cause confidence, the recon score's
    weighted contributors, the readiness score/reason), so the brief can
    never disagree with what Detailed Insights shows for the same payload."""
    total_exceptions = int(total_exceptions or 0)
    if total_exceptions <= 0:
        return ["No reconciliation exceptions were detected; source and target datasets are fully aligned for the analyzed scope."]

    bullets = [f"{total_exceptions} exception{'s' if total_exceptions != 1 else ''} identified."]

    root_causes = root_causes or []
    if root_causes:
        bullets.append(f"Primary issue is {root_causes[0]['cause'].lower()} between source and target systems.")

    contributors = (score_breakdown or {}).get("contributors") or []
    dominant = contributors[0] if contributors else None
    if dominant and dominant.get("count", 0) > 0:
        bullets.append(f"{dominant['name']} account for {dominant['sharePct']}% of reconciliation failures.")

    if readiness:
        readiness_score = float(readiness.get("score", 100) or 0)
        reason = readiness.get("reason") or ""
        reason = reason[:1].lower() + reason[1:] if reason else ""
        band = _readiness_band(readiness_score)
        suffix = f" — {reason}" if reason else ""
        bullets.append(f"Readiness remains {band} at {int(round(readiness_score))}%{suffix}")

    if dominant and dominant.get("penaltyPoints", 0) > 0:
        bullets.append(
            f"Resolving {dominant['name'].lower()} could improve reconciliation accuracy by "
            f"approximately {int(round(dominant['penaltyPoints']))}%."
        )

    return bullets


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

        duplicate_records = detect_duplicate_records(df)
        mapping_failure_records = self._count_mapping_failure_records(missing_df, extra_df, detections)

        root_cause_explorer = self._build_root_cause_explorer(payload, detections)
        situation_room = self._build_situation_room(
            payload,
            readiness,
            detections,
            type_counts,
            duplicate_records=duplicate_records,
            mapping_failure_records=mapping_failure_records,
        )

        total_exceptions = situation_room["totalExceptions"]
        top_cause_labels = [c["cause"] for c in root_cause_explorer[:2]]

        hotspots = self._build_hotspots(mismatches, payload)
        self._apply_concentration_driver(situation_room, hotspots)

        return {
            "situationRoom": situation_room,
            "exceptionLandscape": self._build_exception_landscape(payload, type_counts),
            "rootCauseExplorer": root_cause_explorer,
            "hotspots": hotspots,
            "businessImpact": self._build_business_impact(payload),
            "patternIntelligence": self._build_pattern_intelligence(payload),
            "actionCenter": self._build_action_center(payload, root_cause_explorer),
            "executiveBrief": generate_executive_brief(
                total_exceptions=total_exceptions,
                top_cause_labels=top_cause_labels,
                readiness_score=float(readiness.get("score", 100) or 100),
            ),
            "executiveBriefBullets": generate_executive_brief_bullets(
                total_exceptions=total_exceptions,
                root_causes=root_cause_explorer,
                score_breakdown=situation_room.get("reconciliationScoreBreakdown"),
                readiness=readiness,
            ),
        }

    # ----------------------------
    # Confidence: exception-concentration driver (needs hotspots, computed
    # after situationRoom, so applied as a small post-process step)
    # ----------------------------
    def _apply_concentration_driver(self, situation_room: dict, hotspots: dict) -> None:
        top_entity = None
        top_share = 0.0
        for dimension in ("plants", "materials"):
            entities = hotspots.get(dimension) or []
            if entities and entities[0]["share"] > top_share:
                top_share = entities[0]["share"]
                top_entity = entities[0]["entity"]

        if not top_entity or top_share < 50:
            return

        drivers = situation_room.get("confidence", {}).get("drivers")
        if drivers is None:
            return

        drivers.append({
            "name": "Exception Concentration",
            "status": "Fail" if top_share >= 70 else "Partial",
            "shortLabel": driver_short_label("Exception Concentration"),
            "detail": f"{top_share}% of exceptions concentrate in {top_entity}.",
            "weightPct": None,
        })

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
        affected_records = int(len(missing_dates) + len(extra_dates))

        return {
            "overlapPct": overlap_pct,
            "confidence": confidence,
            "affectedRecords": affected_records,
            "evidence": (
                f"Source-side records span {m_start.date()}–{m_end.date()}; "
                f"target-only records span {e_start.date()}–{e_end.date()} "
                f"({overlap_pct}% date-range overlap)."
            ),
            "reasoning": f"Confidence = 100% − {overlap_pct}% date-range overlap between source-only and target-only records.",
            "metrics": {
                "overlapPct": overlap_pct,
                "affectedRecords": affected_records,
                "spanDays": span_days,
                "overlapDays": overlap_days,
            },
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
        affected_records = int(len(missing_df) + len(extra_df))

        return {
            "overlapPct": overlap_pct,
            "confidence": confidence,
            "affectedRecords": affected_records,
            "evidence": (
                f"Only {len(intersection)} of {len(union)} distinct values are shared between "
                f"source-only and target-only records ({overlap_pct}% overlap)."
            ),
            "reasoning": (
                f"Confidence = 100% − {overlap_pct}% shared-value overlap "
                f"({len(intersection)} of {len(union)} distinct values shared)."
            ),
            "metrics": {
                "overlapPct": overlap_pct,
                "affectedRecords": affected_records,
                "sharedValues": len(intersection),
                "totalDistinctValues": len(union),
            },
            "col": col,
            "unmappedInMissing": missing_vals - intersection,
            "unmappedInExtra": extra_vals - intersection,
        }

    # ----------------------------
    # Mapping-failure record counting (feeds Recon Score breakdown)
    # ----------------------------
    def _count_mapping_failure_records(self, missing_df: pd.DataFrame, extra_df: pd.DataFrame, detections: dict) -> int:
        """Counts rows specifically explained by a detected mapping gap — i.e.
        missing/extra rows whose material or plant value falls outside the
        shared intersection identified by `_detect_mapping_gap` — rather than
        double-counting every missing/extra row as a mapping failure."""
        flagged_missing: set = set()
        flagged_extra: set = set()

        for key in ("productMappingGap", "locationMappingGap"):
            d = detections.get(key)
            if not d:
                continue
            col = d.get("col")
            if not col:
                continue
            if col in missing_df.columns:
                unmapped = d.get("unmappedInMissing") or set()
                mask = missing_df[col].fillna("Unknown").astype(str).isin(unmapped)
                flagged_missing.update(missing_df.index[mask])
            if col in extra_df.columns:
                unmapped = d.get("unmappedInExtra") or set()
                mask = extra_df[col].fillna("Unknown").astype(str).isin(unmapped)
                flagged_extra.update(extra_df.index[mask])

        return len(flagged_missing) + len(flagged_extra)

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
    def _build_situation_room(
        self,
        payload: dict,
        readiness: dict,
        detections: dict,
        type_counts: dict,
        duplicate_records: int = 0,
        mapping_failure_records: int = 0,
    ) -> dict:
        summary = payload.get("summary") or {}
        risk = payload.get("risk") or {}

        total_records = int(summary.get("totalRecords", 0) or 0)
        readiness_score = float(readiness.get("score", 0) or 0)

        missing = int(type_counts.get("Missing in Target", 0) or 0)
        extra = int(type_counts.get("Extra in Target", 0) or 0)
        qty = int(type_counts.get("Quantity Mismatch", 0) or 0)

        score_breakdown = compute_reconciliation_score_breakdown(
            total_records=total_records,
            record_mismatches=missing + extra,
            mapping_failures=mapping_failure_records,
            quantity_variances=qty,
            duplicate_records=duplicate_records,
        )
        recon_score = score_breakdown["score"]

        system_health = classify_system_health(summary.get("severity"), risk.get("category"))
        confidence = {
            "score": int(round(readiness_score)),
            "drivers": self._confidence_drivers(readiness.get("factors") or []),
        }

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
            "reconciliationScoreBreakdown": score_breakdown,
            "totalExceptions": int(summary.get("mismatchedRecords", 0) or 0),
            "severity": summary.get("severity", "Low"),
            "confidenceLevel": confidence_label(readiness_score),
            "confidence": confidence,
            "systemHealth": system_health,
            "narrative": narrative,
            "readiness": readiness,
        }

    def _confidence_drivers(self, factors: list[dict]) -> list[dict]:
        """What's actually moving the confidence number: factors dragging it
        down (Partial/Fail) take priority; if everything passes, surface the
        passing factors instead so confidence isn't a number with no story."""
        if not factors:
            return []

        non_passing = [f for f in factors if f.get("status") != "Pass"]
        source = non_passing if non_passing else factors

        drivers = [
            {
                "name": f.get("name"),
                "status": f.get("status"),
                "detail": f.get("detail"),
                "weightPct": f.get("weightPct"),
                "shortLabel": f.get("shortLabel") or driver_short_label(f.get("name")),
            }
            for f in source
        ]
        return sorted(drivers, key=lambda d: d.get("weightPct") or 0, reverse=True)

    # ----------------------------
    # Exception Landscape
    # ----------------------------
    def _build_exception_landscape(self, payload: dict, type_counts: dict) -> dict:
        summary = payload.get("summary") or {}
        total = int(summary.get("mismatchedRecords", 0) or 0)
        business_impacts = payload.get("businessImpacts") or []

        def pct(n: int) -> float:
            return round(n / total * 100.0, 1) if total else 0.0

        missing = int(type_counts.get("Missing in Target", 0) or 0)
        extra = int(type_counts.get("Extra in Target", 0) or 0)
        qty = int(type_counts.get("Quantity Mismatch", 0) or 0)

        missing_pct, extra_pct, qty_pct = pct(missing), pct(extra), pct(qty)
        high_severity_areas = sum(1 for b in business_impacts if b.get("severity") == "High")

        return {
            "missing": {"count": missing, "distributionPct": missing_pct, "severityContribution": severity_contribution(missing_pct)},
            "extra": {"count": extra, "distributionPct": extra_pct, "severityContribution": severity_contribution(extra_pct)},
            "qtyMismatch": {"count": qty, "distributionPct": qty_pct, "severityContribution": severity_contribution(qty_pct)},
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
                    "reasoning": d.get("reasoning"),
                    "metrics": d.get("metrics"),
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
                "reasoning": self._engine_cause_reasoning(rc),
                "metrics": {"confidence": confidence, "affectedRecords": total_exceptions, "internalCause": rc.get("cause")},
            })

        return sorted(causes, key=lambda c: c["confidence"], reverse=True)[:6]

    def _engine_cause_reasoning(self, rc: dict) -> str:
        formula = _ENGINE_CAUSE_FORMULA.get(
            rc.get("cause"), "Derived from the dominant mismatch-type share within total exceptions."
        )
        return f"{formula} Computed confidence: {rc.get('confidence')}%."

    # ----------------------------
    # Hotspots
    # ----------------------------
    def _build_hotspots(self, mismatches: pd.DataFrame, payload: dict) -> dict:
        plant_col = self._engine._detect_column(mismatches, _PLANT_CANDIDATES) if mismatches is not None and not mismatches.empty else None
        material_col = self._engine._detect_column(mismatches, _MATERIAL_CANDIDATES) if mismatches is not None and not mismatches.empty else None

        return {
            "plants": self._build_hotspot_entities(mismatches, plant_col),
            "materials": self._build_hotspot_entities(mismatches, material_col),
            "dates": self._top_dates(mismatches),
            "matrix": self._build_hotspot_matrix(mismatches),
        }

    def _issue_diagnostics(self, mismatches: pd.DataFrame, mask: pd.Series, total: int) -> dict:
        """Actionable per-hotspot diagnostics: how many of each exception type
        this entity/date contributes, plus a risk contribution weighted by how
        severe its share of total exceptions is — not just a bare percentage."""
        count = int(mask.sum())
        share = round(count / max(1, total) * 100.0, 1)

        if "Remarks" in mismatches.columns:
            entity_remarks = mismatches.loc[mask, "Remarks"].fillna("").astype(str)
            issue_breakdown = {
                "missing": int(entity_remarks.str.contains(_MISSING_RE, case=False, na=False).sum()),
                "extra": int(entity_remarks.str.contains(_EXTRA_RE, case=False, na=False).sum()),
                "qtyMismatch": int(entity_remarks.str.contains(_QTY_MISMATCH_RE, case=False, na=False).sum()),
            }
        else:
            issue_breakdown = {"missing": 0, "extra": 0, "qtyMismatch": 0}

        tier = severity_contribution(share)
        return {
            "mismatchCount": count,
            "share": share,
            "issueBreakdown": issue_breakdown,
            "riskTier": tier,
            "riskContribution": round(share * _SEVERITY_WEIGHT[tier], 1),
        }

    def _build_hotspot_entities(self, mismatches: pd.DataFrame, dimension_col: str | None, limit: int = 10) -> list[dict]:
        if mismatches is None or mismatches.empty or not dimension_col or dimension_col not in mismatches.columns:
            return []

        total = len(mismatches)
        values = mismatches[dimension_col].fillna("Unknown").astype(str)
        top_entities = values.value_counts().head(limit).index

        return [
            {"entity": str(entity), **self._issue_diagnostics(mismatches, values == entity, total)}
            for entity in top_entities
        ]

    def _top_dates(self, mismatches: pd.DataFrame, limit: int = 10) -> list[dict]:
        if mismatches is None or mismatches.empty:
            return []
        date_col = self._engine._detect_column(mismatches, _DATE_CANDIDATES)
        if not date_col or date_col not in mismatches.columns:
            return []

        dt = pd.to_datetime(mismatches[date_col], errors="coerce")
        valid = dt.notna()
        if not valid.any():
            return []

        total = len(mismatches)
        date_strs = dt.dt.date.astype(str)
        top_dates = date_strs[valid].value_counts().head(limit).index

        return [
            {"date": str(date_str), **self._issue_diagnostics(mismatches, valid & (date_strs == date_str), total)}
            for date_str in top_dates
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
    # Pattern Intelligence (gated — hidden entirely below confidence threshold)
    # ----------------------------
    def _build_pattern_intelligence(self, payload: dict, min_confidence: int = 70) -> dict:
        patterns = payload.get("patterns") or []
        strong = [p for p in patterns if int(p.get("confidence", 0) or 0) >= min_confidence]
        return {"show": bool(strong), "patterns": strong[:6]}

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
