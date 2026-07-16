from __future__ import annotations

from backend.recon_engine.models.results import (
    ReconciliationSummary,
    RecordClass,
    excluded_unmapped_counts,
)


def test_excluded_unmapped_counts_sums_row_count_per_field():
    held_out = [
        {"field": "Material", "source_value": "MAT-B", "row_count": 3},
        {"field": "Material", "source_value": "MAT-C", "row_count": 2},
        {"field": "ProductionPlant", "source_value": "PL99", "row_count": 1},
        {"field": "RequestedDeliveryDate", "source_value": None, "row_count": 4},
    ]
    material, plant = excluded_unmapped_counts(held_out)
    assert material == 5
    assert plant == 1


def test_excluded_unmapped_counts_empty_held_out_is_zero():
    assert excluded_unmapped_counts([]) == (0, 0)


def test_summary_excluded_fields_default_to_zero_and_are_additive():
    # from_counts only ever sets the five RecordClass fields; the excluded
    # fields default to 0 and total is unaffected by them, so they're purely
    # additive rather than a restructuring of the existing classification.
    summary = ReconciliationSummary.from_counts({RecordClass.MATCH.value: 2})
    assert summary.excluded_material_unmapped == 0
    assert summary.excluded_plant_unmapped == 0
    assert summary.total == 2

    summary.excluded_material_unmapped = 5
    summary.excluded_plant_unmapped = 1
    assert summary.total == 2  # unaffected by setting excluded counts afterward
