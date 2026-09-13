"""Per-run accumulator for value-pairing decisions (in-memory).

Each date-batch of a streaming run resolves its own product/location
``ValueMapping`` against only that batch's slice of data. This module
accumulates every batch's resolved matches, keyed by (graph_run_id,
source_field, target_field, source_value), so a run's full value-mapping
picture can be reconstructed afterward for reporting (see
``service._effective_contract``). Empty for Manual-mode runs, since nothing
ever calls :func:`record_batch_mapping` for them.
"""

from __future__ import annotations

from backend.recon_engine.models.value_mapping import ValueMapping, ValueMatch

# (graph_run_id, source_field, target_field, source_value) -> match dict
_RUN_MATCHES: dict[tuple[str, str, str, str], dict] = {}
# (graph_run_id, batch_id, source_field, target_field, source_value) -> match dict
_BATCH_MATCHES: dict[tuple[str, str, str, str, str], dict] = {}


def record_batch_mapping(
    graph_run_id: str, value_mapping: ValueMapping, *, batch_id: str | None = None
) -> None:
    """Merges one batch's resolved matches into the running per-run state.

    A given source_value's pairing decision is deterministic for a
    (source_connector, target_connector, source_field, target_field) — batches
    only differ in WHICH source values they saw, not how a shared one
    resolves — so a later batch's match for an already-seen source_value
    simply overwrites the stored one (same decision, refreshed field data);
    ``row_count`` is summed across batches instead, since each batch only
    counts its own slice of rows.
    """
    if not value_mapping.matches:
        return
    for m in value_mapping.matches:
        key = (graph_run_id, value_mapping.source_field, value_mapping.target_field, m.source_value)
        row_count = m.row_count
        prior = _RUN_MATCHES.get(key)
        if prior is not None:
            row_count += int(prior["match"].get("row_count") or 0)
        match_dict = m.model_dump(mode="json")
        match_dict["row_count"] = row_count
        _RUN_MATCHES[key] = {
            "field_mapping_id": value_mapping.field_mapping_id,
            "target_value": m.target_value,
            "match": match_dict,
        }

        if batch_id is not None:
            batch_key = (graph_run_id, batch_id, value_mapping.source_field, value_mapping.target_field, m.source_value)
            _BATCH_MATCHES[batch_key] = {
                "field_mapping_id": value_mapping.field_mapping_id,
                "target_value": m.target_value,
                "match": m.model_dump(mode="json"),
            }


def get_run_mappings(graph_run_id: str) -> list[ValueMapping]:
    """Every accumulated ``ValueMapping`` for this run, one per (source_field,
    target_field) pair actually resolved by some batch — empty for
    Manual-mode runs (nothing was ever recorded under their run_id)."""
    grouped: dict[tuple[str, str], list[ValueMatch]] = {}
    field_mapping_ids: dict[tuple[str, str], str | None] = {}
    for (rid, sf, tf, _sv), entry in _RUN_MATCHES.items():
        if rid != graph_run_id:
            continue
        key = (sf, tf)
        grouped.setdefault(key, []).append(ValueMatch.model_validate(entry["match"]))
        field_mapping_ids[key] = entry["field_mapping_id"]
    return [
        ValueMapping(source_field=sf, target_field=tf, matches=matches, field_mapping_id=field_mapping_ids[(sf, tf)])
        for (sf, tf), matches in grouped.items()
    ]


def get_batch_mappings(graph_run_id: str, batch_id: str) -> list[ValueMapping]:
    """Every ``ValueMapping`` THIS SPECIFIC batch resolved — the batch-scoped
    counterpart to :func:`get_run_mappings`'s run-wide cumulative picture."""
    grouped: dict[tuple[str, str], list[ValueMatch]] = {}
    field_mapping_ids: dict[tuple[str, str], str | None] = {}
    for (rid, bid, sf, tf, _sv), entry in _BATCH_MATCHES.items():
        if rid != graph_run_id or bid != batch_id:
            continue
        key = (sf, tf)
        grouped.setdefault(key, []).append(ValueMatch.model_validate(entry["match"]))
        field_mapping_ids[key] = entry["field_mapping_id"]
    return [
        ValueMapping(source_field=sf, target_field=tf, matches=matches, field_mapping_id=field_mapping_ids[(sf, tf)])
        for (sf, tf), matches in grouped.items()
    ]
