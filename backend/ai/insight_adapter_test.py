"""Unit tests for the pure (non-DataFrame) helpers in insight_adapter.py.

Run with: venv/Scripts/python.exe -m pytest backend/ai/insight_adapter_test.py -v
"""

from backend.ai.insight_adapter import (
    classify_system_health,
    compute_reconciliation_score_breakdown,
    compute_readiness_score,
    confidence_label,
    detect_duplicate_records,
    driver_short_label,
    generate_executive_brief,
    generate_executive_brief_bullets,
    generate_executive_narrative,
    map_area_to_risk_lens,
    map_cause_to_taxonomy,
    readiness_status_for,
    severity_contribution,
)


# ----------------------------
# compute_reconciliation_score_breakdown
# ----------------------------
def test_reconciliation_score_breakdown_no_issues_is_100():
    result = compute_reconciliation_score_breakdown(
        total_records=100, record_mismatches=0, mapping_failures=0, quantity_variances=0, duplicate_records=0
    )
    assert result["score"] == 100
    assert all(c["penaltyPoints"] == 0 for c in result["contributors"])


def test_reconciliation_score_breakdown_every_record_affected_is_0():
    result = compute_reconciliation_score_breakdown(
        total_records=100, record_mismatches=100, mapping_failures=100, quantity_variances=100, duplicate_records=100
    )
    assert result["score"] == 0


def test_reconciliation_score_breakdown_penalties_sum_to_deduction():
    result = compute_reconciliation_score_breakdown(
        total_records=200, record_mismatches=40, mapping_failures=10, quantity_variances=20, duplicate_records=5
    )
    total_penalty = sum(c["penaltyPoints"] for c in result["contributors"])
    assert result["score"] == round(100 - total_penalty)


def test_reconciliation_score_breakdown_contribution_pct_sums_to_100():
    result = compute_reconciliation_score_breakdown(
        total_records=200, record_mismatches=40, mapping_failures=10, quantity_variances=20, duplicate_records=5
    )
    assert round(sum(c["contributionPct"] for c in result["contributors"]), 0) == 100


def test_reconciliation_score_breakdown_zero_total_records_is_100():
    result = compute_reconciliation_score_breakdown(
        total_records=0, record_mismatches=0, mapping_failures=0, quantity_variances=0, duplicate_records=0
    )
    assert result["score"] == 100


def test_reconciliation_score_breakdown_handles_none_inputs():
    result = compute_reconciliation_score_breakdown(None, None, None, None, None)
    assert result["score"] == 100


# ----------------------------
# detect_duplicate_records
# ----------------------------
def test_detect_duplicate_records_flags_full_row_duplicates():
    import pandas as pd

    df = pd.DataFrame({
        "Material": ["A", "A", "B"],
        "Plant": ["P1", "P1", "P2"],
        "Remarks": ["✅ MATCH", "⚠️ QTY MISMATCH", "✅ MATCH"],
    })
    assert detect_duplicate_records(df) == 2


def test_detect_duplicate_records_no_duplicates_is_zero():
    import pandas as pd

    df = pd.DataFrame({"Material": ["A", "B"], "Plant": ["P1", "P2"], "Remarks": ["", ""]})
    assert detect_duplicate_records(df) == 0


def test_detect_duplicate_records_empty_df_is_zero():
    import pandas as pd

    assert detect_duplicate_records(pd.DataFrame()) == 0


# ----------------------------
# severity_contribution
# ----------------------------
def test_severity_contribution_thresholds():
    assert severity_contribution(60) == "High"
    assert severity_contribution(20) == "Medium"
    assert severity_contribution(5) == "Low"


# ----------------------------
# classify_system_health
# ----------------------------
def test_system_health_high_severity_is_degraded():
    assert classify_system_health("High", "Low") == "Degraded"


def test_system_health_critical_risk_is_degraded():
    assert classify_system_health("Low", "Critical") == "Degraded"


def test_system_health_medium_is_attention_needed():
    assert classify_system_health("Medium", "Low") == "Attention Needed"


def test_system_health_low_everything_is_healthy():
    assert classify_system_health("Low", "Low") == "Healthy"


# ----------------------------
# confidence_label
# ----------------------------
def test_confidence_label_thresholds():
    assert confidence_label(85) == "High"
    assert confidence_label(70) == "High"
    assert confidence_label(55) == "Medium"
    assert confidence_label(40) == "Medium"
    assert confidence_label(10) == "Low"


# ----------------------------
# map_cause_to_taxonomy / map_area_to_risk_lens
# ----------------------------
def test_map_cause_to_taxonomy_known_causes():
    assert map_cause_to_taxonomy("Timing Delay") == "Date Range Mismatch"
    assert map_cause_to_taxonomy("Master Data Issue") == "Master Data Misalignment"
    assert map_cause_to_taxonomy("Mapping or Synchronization Issue") == "Missing Transactions"


def test_map_cause_to_taxonomy_unknown_defaults_to_master_data():
    assert map_cause_to_taxonomy("Something New") == "Master Data Misalignment"
    assert map_cause_to_taxonomy(None) == "Master Data Misalignment"


def test_map_area_to_risk_lens_known_areas():
    assert map_area_to_risk_lens("Inventory Planning") == "Inventory Visibility Risk"
    assert map_area_to_risk_lens("Supply Chain") == "Fulfillment Risk"
    assert map_area_to_risk_lens("Compliance") == "Reporting Risk"


def test_map_area_to_risk_lens_unknown_defaults_to_forecast():
    assert map_area_to_risk_lens("Something New") == "Forecast Accuracy Risk"


# ----------------------------
# readiness_status_for
# ----------------------------
def test_readiness_status_thresholds():
    assert readiness_status_for(80) == "Pass"
    assert readiness_status_for(70) == "Pass"
    assert readiness_status_for(55) == "Partial"
    assert readiness_status_for(40) == "Partial"
    assert readiness_status_for(10) == "Fail"


# ----------------------------
# compute_readiness_score
# ----------------------------
def test_readiness_score_no_factors_defaults_to_100_with_caveat():
    result = compute_readiness_score([])
    assert result["score"] == 100
    assert "available" in result["reason"].lower()


def test_readiness_score_all_pass_is_100():
    factors = [
        {"name": "A", "status": "Pass", "weight": 1.0},
        {"name": "B", "status": "Pass", "weight": 2.0},
    ]
    result = compute_readiness_score(factors)
    assert result["score"] == 100
    assert "trustworthy" in result["reason"].lower()


def test_readiness_score_all_fail_is_0():
    factors = [
        {"name": "Date Range Overlap", "status": "Fail", "weight": 1.0},
    ]
    result = compute_readiness_score(factors)
    assert result["score"] == 0
    assert "Date Range Overlap" in result["reason"]


def test_readiness_score_mixed_weights_partial_credit():
    factors = [
        {"name": "A", "status": "Pass", "weight": 1.0},
        {"name": "B", "status": "Fail", "weight": 1.0},
    ]
    result = compute_readiness_score(factors)
    assert result["score"] == 50


def test_readiness_score_enriches_factors_with_weighted_breakdown():
    factors = [
        {"name": "A", "status": "Pass", "weight": 1.0},
        {"name": "B", "status": "Partial", "weight": 3.0},
    ]
    result = compute_readiness_score(factors)
    a, b = result["factors"]
    assert a["statusScore"] == 1.0 and b["statusScore"] == 0.5
    assert a["weightPct"] == 25.0 and b["weightPct"] == 75.0
    assert a["contributionPoints"] == 25.0 and b["contributionPoints"] == 37.5
    assert "formula" in result


def test_readiness_score_reflects_this_conversations_example():
    # Mirrors the "1210 missing / 1000 extra, non-overlapping periods" scenario
    # from the design discussion: date overlap fails -> low readiness.
    factors = [
        {"name": "Record Key Overlap", "status": "Fail", "weight": 1.5},
        {"name": "Date Range Overlap", "status": "Fail", "weight": 1.5},
        {"name": "Material Mapping Coverage", "status": "Pass", "weight": 1.0},
    ]
    result = compute_readiness_score(factors)
    assert result["score"] < 40
    assert "Record Key Overlap" in result["reason"]
    assert "Date Range Overlap" in result["reason"]


# ----------------------------
# generate_executive_narrative
# ----------------------------
def test_narrative_no_exceptions():
    text = generate_executive_narrative(0, 0, 0)
    assert "aligned" in text.lower()


def test_narrative_missing_and_extra_with_causes():
    text = generate_executive_narrative(
        missing_count=1210,
        extra_count=1000,
        qty_count=0,
        top_cause_labels=["date-range inconsistencies", "master-data mapping gaps"],
        readiness_low=True,
    )
    assert "1210 records are missing in target systems" in text
    assert "1000 additional records exist only in target" in text
    assert "date-range inconsistencies" in text
    assert "No direct matches were identified" in text


def test_narrative_without_causes_omits_cause_sentence():
    text = generate_executive_narrative(missing_count=5, extra_count=0, qty_count=0)
    assert text == "5 records are missing in target systems."


def test_narrative_qty_only():
    text = generate_executive_narrative(missing_count=0, extra_count=0, qty_count=12)
    assert "12 records show quantity mismatches" in text


def test_narrative_high_readiness_uses_driver_phrasing_not_no_match_phrasing():
    text = generate_executive_narrative(
        missing_count=3, extra_count=0, qty_count=0, top_cause_labels=["quantity variance"], readiness_low=False,
    )
    assert "primary driver is quantity variance" in text
    assert "No direct matches" not in text


# ----------------------------
# generate_executive_brief
# ----------------------------
def test_executive_brief_no_exceptions():
    text = generate_executive_brief(0, [], 100)
    assert "no exceptions" in text.lower()


def test_executive_brief_low_readiness_includes_caveat():
    text = generate_executive_brief(2210, ["Date Range Mismatch", "Master Data Misalignment"], readiness_score=35)
    assert "2210 exceptions" in text
    assert "date range mismatch" in text.lower()
    assert "master-data harmonization" in text.lower()


def test_executive_brief_high_readiness_omits_caveat():
    text = generate_executive_brief(10, ["Quantity Variance"], readiness_score=90)
    assert "10 exceptions" in text
    assert "master-data harmonization" not in text.lower()


# ----------------------------
# driver_short_label
# ----------------------------
def test_driver_short_label_known_names():
    assert driver_short_label("Record Key Overlap") == "Low key overlap"
    assert driver_short_label("Date Range Overlap") == "Misaligned date ranges"


def test_driver_short_label_unknown_returns_none():
    assert driver_short_label("Something Else") is None
    assert driver_short_label(None) is None


# ----------------------------
# generate_executive_brief_bullets
# ----------------------------
def test_brief_bullets_no_exceptions():
    bullets = generate_executive_brief_bullets(0, [], None, None)
    assert len(bullets) == 1
    assert "aligned" in bullets[0].lower()


def test_brief_bullets_names_dominant_contributor():
    score_breakdown = compute_reconciliation_score_breakdown(
        total_records=100, record_mismatches=10, mapping_failures=67, quantity_variances=5, duplicate_records=0
    )
    bullets = generate_executive_brief_bullets(
        total_exceptions=6,
        root_causes=[{"cause": "Product Mapping Gap", "confidence": 87}],
        score_breakdown=score_breakdown,
        readiness={"score": 21, "reason": "Poor mapping coverage indicates the datasets may not be directly comparable."},
    )
    assert bullets[0] == "6 exceptions identified."
    assert "primary issue is product mapping gap" in bullets[1].lower()
    assert any("Mapping Failures account for" in b for b in bullets)
    assert any("Readiness remains low at 21%" in b for b in bullets)


def test_brief_bullets_improvement_uses_penalty_points():
    score_breakdown = compute_reconciliation_score_breakdown(
        total_records=100, record_mismatches=0, mapping_failures=100, quantity_variances=0, duplicate_records=0
    )
    dominant_penalty = score_breakdown["contributors"][0]["penaltyPoints"]
    bullets = generate_executive_brief_bullets(
        total_exceptions=6,
        root_causes=[],
        score_breakdown=score_breakdown,
        readiness={"score": 50, "reason": "Some caution advised."},
    )
    assert any(f"approximately {int(round(dominant_penalty))}%" in b for b in bullets)


def test_brief_bullets_no_readiness_or_causes_still_returns_count():
    bullets = generate_executive_brief_bullets(3, None, None, None)
    assert bullets[0] == "3 exceptions identified."
    assert len(bullets) == 1
