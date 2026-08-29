"""Per-run accumulator for Auto-mode value-pairing decisions.

Each date-batch of an Auto-mode streaming run (see
``auto_pipeline.nodes._do_run_batches``) resolves its own product/location
``ValueMapping`` against only that batch's slice of data, folded into a
throwaway per-batch contract copy that is never written back to
``contract_store`` — there is no single "the contract's value_mappings" for
an Auto-mode run the way there is for Manual mode, whose approved contract
carries the full mapping directly. This module accumulates every batch's
resolved matches, keyed by (graph_run_id, source_field, target_field,
source_value), so a run's full value-mapping picture can be reconstructed
afterward for reporting (see ``service._effective_contract``) — the same
data Manual mode already carries on its contract.
"""

from __future__ import annotations

import json

from backend.recon_engine.models.value_mapping import ValueMapping, ValueMatch
from backend.recon_engine.storage.db import main_db


def record_batch_mapping(graph_run_id: str, value_mapping: ValueMapping) -> None:
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
    with main_db() as conn:
        for m in value_mapping.matches:
            row = conn.execute(
                """SELECT match_json FROM run_value_mapping_matches
                   WHERE graph_run_id = ? AND source_field = ? AND target_field = ?
                     AND source_value = ?""",
                (graph_run_id, value_mapping.source_field, value_mapping.target_field, m.source_value),
            ).fetchone()
            row_count = m.row_count
            if row is not None:
                prior = json.loads(row["match_json"])
                row_count += int(prior.get("row_count") or 0)
            match_dict = json.loads(m.model_dump_json())
            match_dict["row_count"] = row_count
            conn.execute(
                """INSERT INTO run_value_mapping_matches
                   (graph_run_id, source_field, target_field, field_mapping_id,
                    source_value, target_value, match_json)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT (graph_run_id, source_field, target_field, source_value)
                   DO UPDATE SET target_value = excluded.target_value,
                                 field_mapping_id = excluded.field_mapping_id,
                                 match_json = excluded.match_json""",
                (
                    graph_run_id, value_mapping.source_field, value_mapping.target_field,
                    value_mapping.field_mapping_id, m.source_value, m.target_value,
                    json.dumps(match_dict),
                ),
            )


def get_run_mappings(graph_run_id: str) -> list[ValueMapping]:
    """Every accumulated ``ValueMapping`` for this run, one per (source_field,
    target_field) pair actually resolved by some batch — empty for
    Manual-mode runs (nothing was ever recorded under their run_id) or an
    Auto-mode run with no value-mapped business key at all."""
    with main_db() as conn:
        rows = conn.execute(
            """SELECT source_field, target_field, field_mapping_id, match_json
               FROM run_value_mapping_matches WHERE graph_run_id = ?
               ORDER BY source_field, target_field, source_value""",
            (graph_run_id,),
        ).fetchall()
    grouped: dict[tuple[str, str], list[ValueMatch]] = {}
    field_mapping_ids: dict[tuple[str, str], str | None] = {}
    for row in rows:
        key = (row["source_field"], row["target_field"])
        grouped.setdefault(key, []).append(ValueMatch.model_validate_json(row["match_json"]))
        field_mapping_ids[key] = row["field_mapping_id"]
    return [
        ValueMapping(source_field=sf, target_field=tf, matches=matches, field_mapping_id=field_mapping_ids[(sf, tf)])
        for (sf, tf), matches in grouped.items()
    ]
