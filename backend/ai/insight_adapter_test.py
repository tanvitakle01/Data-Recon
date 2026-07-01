"""Unit tests for the pure (non-DataFrame) helpers in insight_adapter.py.

Run with: venv/Scripts/python.exe -m pytest backend/ai/insight_adapter_test.py -v
"""

from backend.ai.insight_adapter import (
    classify_system_health,
    compute_reconciliation_score,
    compute_readiness_score,
    confidence_label,
    generate_executive_narrative,
    map_area_to_risk_lens,
    map_cause_to_taxonomy,
    readiness_status_for,
)


# ----------------------------
# compute_reconciliation_score
# ----------------------------
def test_reconciliation_score_perfect_inputs_is_100():
    assert compute_reconciliation_score(accuracy=100, risk_score=0, readiness_score=100) == 100


def test_reconciliation_score_worst_inputs_is_0():
    assert compute_reconciliation_score(accuracy=0, risk_score=100, readiness_score=0) == 0


def test_reconciliation_score_differs_from_raw_accuracy_when_readiness_low():
    # Same accuracy, but low readiness should pull the composite score below accuracy.
    high_readiness = compute_reconciliation_score(accuracy=90, risk_score=10, readiness_score=90)
    low_readiness = compute_reconciliation_score(accuracy=90, risk_score=10, readiness_score=20)
    assert low_readiness < high_readiness


def test_reconciliation_score_handles_none_inputs():
    # None accuracy/readiness -> 0, but None risk_score also means "no known risk" (0),
    # which contributes +30 via the (100 - risk_score) * 0.3 term.
    assert compute_reconciliation_score(None, None, None) == 30


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
