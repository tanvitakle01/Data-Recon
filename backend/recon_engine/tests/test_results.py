from __future__ import annotations

from backend.recon_engine.models.results import (
    ReconciliationSummary,
    RecordClass,
    excluded_unmapped_counts,
)


def test_excluded_unmapped_counts_sums_row_count_per_field():
    # Sums per SOURCE field name generically — any business-key field that
    # held out rows appears, not just Material/Plant (RequestedDeliveryDate
    # included here on purpose).
    held_out = [
        {"field": "Material", "source_value": "MAT-B", "row_count": 3},
        {"field": "Material", "source_value": "MAT-C", "row_count": 2},
        {"field": "ProductionPlant", "source_value": "PL99", "row_count": 1},
        {"field": "RequestedDeliveryDate", "source_value": None, "row_count": 4},
    ]
    assert excluded_unmapped_counts(held_out) == {
        "Material": 5,
        "ProductionPlant": 1,
        "RequestedDeliveryDate": 4,
    }


def test_excluded_unmapped_counts_empty_held_out_is_zero():
    assert excluded_unmapped_counts([]) == {}


def test_summary_excluded_fields_default_to_zero_and_are_additive():
    # from_counts only ever sets the five RecordClass fields; excluded_unmapped
    # defaults to an empty dict and total is unaffected by it, so it's purely
    # additive rather than a restructuring of the existing classification.
    summary = ReconciliationSummary.from_counts({RecordClass.MATCH.value: 2})
    assert summary.excluded_unmapped == {}
    assert summary.total == 2

    summary.excluded_unmapped = {"Material": 5, "ProductionPlant": 1}
    assert summary.total == 2  # unaffected by setting excluded counts afterward


def test_summary_from_counts_splits_missing_and_extra_in_target():
    summary = ReconciliationSummary.from_counts({
        RecordClass.MATCH.value: 1,
        RecordClass.MISMATCH.value: 1,
        RecordClass.MISSING_IN_TARGET.value: 2,
        RecordClass.MISSING_IN_SOURCE.value: 3,
    })
    assert summary.missing_in_target == 2
    assert summary.extra_in_target == 3
    assert summary.mismatch == 5  # kept as the sum, for backward compatibility
    assert summary.total == 7


def test_summary_migrates_unified_mismatch_with_no_split_info():
    # A summary persisted while missing_in_target/extra_in_target were
    # unified into one `mismatch` bucket has no way to recover the split —
    # best effort puts the whole total under missing_in_target.
    summary = ReconciliationSummary.model_validate(
        {"total": 4, "match": 1, "quantity_mismatch": 1, "mismatch": 2}
    )
    assert summary.missing_in_target == 2
    assert summary.extra_in_target == 0
    assert summary.mismatch == 2


def test_summary_migrates_oldest_split_format():
    # The oldest persisted format already had the one-sided split, named
    # missing_in_source (target-only)/missing_in_target (source-only).
    summary = ReconciliationSummary.model_validate(
        {
            "total": 4,
            "match": 1,
            "mismatch": 1,  # old field-level name for today's quantity_mismatch
            "missing_in_target": 1,
            "missing_in_source": 1,
        }
    )
    assert summary.quantity_mismatch == 1
    assert summary.missing_in_target == 1
    assert summary.extra_in_target == 1
    assert summary.mismatch == 2


def test_summary_migrates_legacy_excluded_material_plant_fields():
    # Summaries persisted before excluded_unmapped became a generic dict
    # carried two fixed named counters — old data must still load.
    summary = ReconciliationSummary.model_validate(
        {
            "total": 2,
            "match": 2,
            "quantity_mismatch": 0,
            "mismatch": 0,
            "excluded_material_unmapped": 5,
            "excluded_plant_unmapped": 1,
        }
    )
    assert summary.excluded_unmapped == {"Material": 5, "ProductionPlant": 1}
