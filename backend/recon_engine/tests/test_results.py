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
