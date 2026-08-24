"""Incremental corroboration evidence for one Auto-mode streaming run.

``value_pairing.corroborate.corroboration_overlap`` computes a date-overlap
signal from a full, unsliced pair of Series — the streaming batch orchestrator
never holds that. Because a single date is never split across batches (see
``auto_pipeline.date_batching``), any real overlap between a source value and
a target value is always fully visible within whichever ONE batch contains
their shared date, so the running state this module accumulates only needs
three booleans per candidate pair, OR-combined batch over batch — never the
full date sets.
"""

from __future__ import annotations

from backend.recon_engine.storage.db import main_db


def record_batch_evidence(
    graph_run_id: str,
    *,
    source_field: str,
    target_field: str,
    source_value: str,
    target_value: str,
    source_seen: bool,
    target_seen: bool,
    overlap: bool,
) -> None:
    """OR-combines this batch's own within-batch evidence into the running
    state for one candidate pair. Safe to call once per batch per candidate
    pair considered (see ``corroborate.corroboration_overlap``'s caller —
    only fires when a value has more than one competing candidate)."""
    with main_db() as conn:
        row = conn.execute(
            """SELECT source_seen, target_seen, overlap FROM value_pair_corroboration
               WHERE graph_run_id = ? AND source_field = ? AND target_field = ?
                 AND source_value = ? AND target_value = ?""",
            (graph_run_id, source_field, target_field, source_value, target_value),
        ).fetchone()
        merged_source_seen = source_seen or bool(row["source_seen"]) if row else source_seen
        merged_target_seen = target_seen or bool(row["target_seen"]) if row else target_seen
        merged_overlap = overlap or bool(row["overlap"]) if row else overlap
        conn.execute(
            """INSERT INTO value_pair_corroboration
               (graph_run_id, source_field, target_field, source_value, target_value,
                source_seen, target_seen, overlap)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT (graph_run_id, source_field, target_field, source_value, target_value)
               DO UPDATE SET source_seen = excluded.source_seen,
                              target_seen = excluded.target_seen,
                              overlap = excluded.overlap""",
            (
                graph_run_id, source_field, target_field, source_value, target_value,
                int(merged_source_seen), int(merged_target_seen), int(merged_overlap),
            ),
        )


def get_overlap(
    graph_run_id: str,
    *,
    source_field: str,
    target_field: str,
    source_value: str,
    target_value: str,
) -> bool | None:
    """Same semantics as ``corroboration_overlap``: ``None`` means no signal
    (one side never seen a dated row for this value across any batch so far),
    otherwise the accumulated overlap-ever-seen boolean."""
    with main_db() as conn:
        row = conn.execute(
            """SELECT source_seen, target_seen, overlap FROM value_pair_corroboration
               WHERE graph_run_id = ? AND source_field = ? AND target_field = ?
                 AND source_value = ? AND target_value = ?""",
            (graph_run_id, source_field, target_field, source_value, target_value),
        ).fetchone()
    if row is None or not row["source_seen"] or not row["target_seen"]:
        return None
    return bool(row["overlap"])


def clear(graph_run_id: str) -> None:
    """Drops every candidate pair's corroboration state for this run — called
    once the run completes, alongside ``pipeline_run_store.
    clear_batch_checkpoints``."""
    with main_db() as conn:
        conn.execute(
            "DELETE FROM value_pair_corroboration WHERE graph_run_id = ?", (graph_run_id,)
        )
