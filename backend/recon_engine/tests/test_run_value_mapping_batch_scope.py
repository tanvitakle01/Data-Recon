"""Coverage for ``run_value_mapping_store``'s batch-scoped snapshot (see the
``run_batch_value_mappings`` DDL comment in ``storage/db.py``): each batch's
OWN resolved matches must be independently retrievable, distinct from the
run-wide cumulative row ``get_run_mappings`` reconstructs.
"""

from __future__ import annotations

from backend.recon_engine.models.value_mapping import ValueMapping
from backend.recon_engine.storage import run_value_mapping_store


def _mapping(*, source_value, target_value, row_count) -> ValueMapping:
    return ValueMapping.model_validate(
        {
            "source_field": "Material", "target_field": "PRDID",
            "matches": [
                {
                    "source_value": source_value, "target_value": target_value,
                    "confidence": "high", "rule": "t", "evidence": "e", "row_count": row_count,
                }
            ],
        }
    )


def test_get_batch_mappings_returns_only_that_batchs_own_matches():
    run_value_mapping_store.record_batch_mapping(
        "run_1", _mapping(source_value="A", target_value="A1", row_count=3), batch_id="batch_1"
    )
    run_value_mapping_store.record_batch_mapping(
        "run_1", _mapping(source_value="B", target_value="B1", row_count=5), batch_id="batch_2"
    )

    batch_1 = run_value_mapping_store.get_batch_mappings("run_1", "batch_1")
    assert len(batch_1) == 1
    assert [m.source_value for m in batch_1[0].matches] == ["A"]
    assert batch_1[0].matches[0].row_count == 3

    batch_2 = run_value_mapping_store.get_batch_mappings("run_1", "batch_2")
    assert [m.source_value for m in batch_2[0].matches] == ["B"]


def test_get_batch_mappings_is_empty_for_an_unknown_batch():
    assert run_value_mapping_store.get_batch_mappings("run_1", "no_such_batch") == []


def test_batch_scoped_rows_dont_change_the_cumulative_run_wide_view():
    """The pre-existing ``get_run_mappings`` (used by the comparison workbook's
    Mapping Details sheet) must keep merging/overwriting exactly as before —
    batch-id tracking is purely additive."""
    run_value_mapping_store.record_batch_mapping(
        "run_2", _mapping(source_value="A", target_value="A1", row_count=1), batch_id="batch_1"
    )
    run_value_mapping_store.record_batch_mapping(
        "run_2", _mapping(source_value="A", target_value="A1", row_count=2), batch_id="batch_2"
    )

    cumulative = run_value_mapping_store.get_run_mappings("run_2")
    assert len(cumulative) == 1
    assert cumulative[0].matches[0].row_count == 3  # summed across both batches, as before

    # Each batch's own snapshot still reflects only its own row_count.
    assert run_value_mapping_store.get_batch_mappings("run_2", "batch_1")[0].matches[0].row_count == 1
    assert run_value_mapping_store.get_batch_mappings("run_2", "batch_2")[0].matches[0].row_count == 2
