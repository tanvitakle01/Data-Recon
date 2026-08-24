"""Auto-mode pipeline run store — tracks one end-to-end graph execution.

Plain dict rows (not a pydantic model): every field here is either a status
string or an opaque JSON blob (step timestamps, final result) that only ever
needs to round-trip to the polling endpoint, never structural validation.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.recon_engine.storage.db import main_db


def new_graph_run_id() -> str:
    return "autorun_" + uuid.uuid4().hex


def create(graph_run_id: str) -> None:
    with main_db() as conn:
        conn.execute(
            """INSERT INTO pipeline_runs
               (graph_run_id, status, current_step, step_timestamps_json,
                failed_step, error, result_json, created_at, batch_progress_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                graph_run_id, "running", None, json.dumps({}),
                None, None, None, datetime.now(timezone.utc).isoformat(), None,
            ),
        )


def update(
    graph_run_id: str,
    *,
    status: str,
    current_step: str | None = None,
    step_timestamps: dict[str, Any] | None = None,
    failed_step: str | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
    interrupt: dict[str, Any] | None = None,
) -> None:
    """``interrupt`` carries the resolver bot's pending question while
    ``status == "waiting_for_input"`` — callers pass ``None`` explicitly to
    clear a stale one whenever the run isn't actually paused (see
    ``routes/auto_pipeline.py``), never left as a leftover default.
    """
    with main_db() as conn:
        conn.execute(
            """UPDATE pipeline_runs
               SET status = ?, current_step = ?, step_timestamps_json = ?,
                   failed_step = ?, error = ?, result_json = ?, interrupt_json = ?
               WHERE graph_run_id = ?""",
            (
                status,
                current_step,
                json.dumps(step_timestamps or {}),
                failed_step,
                error,
                json.dumps(result) if result is not None else None,
                json.dumps(interrupt) if interrupt is not None else None,
                graph_run_id,
            ),
        )


def update_batch_progress(
    graph_run_id: str,
    *,
    field_pair: str,
    batch_index: int,
    batch_count: int,
    batch_label: str,
) -> None:
    """Live per-batch progress for the currently-running ``pair_values`` call
    (see ``value_pairing.pipeline.pair_values``'s ``on_batch`` hook) — a
    separate write from :func:`update` (which only runs once per WHOLE graph
    node completes) so the polling status endpoint can show "batch N of M"
    while the ``pair_values`` node is still mid-flight.
    """
    with main_db() as conn:
        conn.execute(
            "UPDATE pipeline_runs SET batch_progress_json = ? WHERE graph_run_id = ?",
            (
                json.dumps(
                    {
                        "field_pair": field_pair,
                        "batch_index": batch_index,
                        "batch_count": batch_count,
                        "batch_label": batch_label,
                    }
                ),
                graph_run_id,
            ),
        )


def get_batch_checkpoint(graph_run_id: str, field_pair: str) -> dict[str, Any] | None:
    """The resume point for one field pair's ``pair_values()`` call — how many
    of its batches already resolved (``next_batch_index``) and their combined
    matches so far, or ``None`` if this field pair has no checkpoint yet
    (either it hasn't started, or its ``pair_values`` node already completed
    and :func:`clear_batch_checkpoints` removed it)."""
    with main_db() as conn:
        row = conn.execute(
            """SELECT next_batch_index, batch_count, matches_json
               FROM pipeline_batch_checkpoints WHERE graph_run_id = ? AND field_pair = ?""",
            (graph_run_id, field_pair),
        ).fetchone()
    if row is None:
        return None
    return {
        "next_batch_index": row["next_batch_index"],
        "batch_count": row["batch_count"],
        "matches": json.loads(row["matches_json"]),
    }


def save_batch_checkpoint(
    graph_run_id: str,
    *,
    field_pair: str,
    next_batch_index: int,
    batch_count: int,
    matches: list[dict[str, Any]],
) -> None:
    """Upserts the resume point for one field pair after one of its batches
    resolves — ``matches`` is the FULL accumulated list for this field pair so
    far (the caller reads the prior checkpoint, if any, and extends it), never
    just the newest batch's matches."""
    with main_db() as conn:
        conn.execute(
            """INSERT INTO pipeline_batch_checkpoints
               (graph_run_id, field_pair, next_batch_index, batch_count, matches_json)
               VALUES (?,?,?,?,?)
               ON CONFLICT (graph_run_id, field_pair) DO UPDATE SET
                   next_batch_index = excluded.next_batch_index,
                   batch_count = excluded.batch_count,
                   matches_json = excluded.matches_json""",
            (graph_run_id, field_pair, next_batch_index, batch_count, json.dumps(matches)),
        )


def clear_batch_checkpoints(graph_run_id: str) -> None:
    """Drops every field pair's checkpoint for this run — called once the
    owning ``pair_values`` node completes successfully (nothing left to
    resume) and when a fresh run starts."""
    with main_db() as conn:
        conn.execute(
            "DELETE FROM pipeline_batch_checkpoints WHERE graph_run_id = ?", (graph_run_id,)
        )


def save_run_batch_plan(graph_run_id: str, batches: list[dict[str, Any]]) -> None:
    """Persists the streaming batch plan (see ``auto_pipeline.date_batching.
    plan_batches``) once, computed from the cheap distinct-date-union pull —
    a retry must never recompute this (it would re-run that pull for no
    reason), only read it back via :func:`get_run_batch_plan`."""
    with main_db() as conn:
        conn.execute(
            """INSERT INTO run_batch_plan (graph_run_id, batches_json) VALUES (?, ?)
               ON CONFLICT (graph_run_id) DO UPDATE SET batches_json = excluded.batches_json""",
            (graph_run_id, json.dumps(batches)),
        )


def get_run_batch_plan(graph_run_id: str) -> list[dict[str, Any]] | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT batches_json FROM run_batch_plan WHERE graph_run_id = ?", (graph_run_id,)
        ).fetchone()
    return json.loads(row["batches_json"]) if row else None


def get_run_batch_checkpoint(graph_run_id: str) -> dict[str, Any] | None:
    """The resume point for one run's ``run_batches`` node — which
    ``result_store`` result it's appending to, how many batches already
    completed (``next_batch_index``) — or ``None`` if this run hasn't started
    its batch loop yet, or already completed and cleared it."""
    with main_db() as conn:
        row = conn.execute(
            """SELECT result_id, next_batch_index, batch_count, summary_json
               FROM run_batch_checkpoint WHERE graph_run_id = ?""",
            (graph_run_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "result_id": row["result_id"],
        "next_batch_index": row["next_batch_index"],
        "batch_count": row["batch_count"],
        "summary": json.loads(row["summary_json"]),
    }


def save_run_batch_checkpoint(
    graph_run_id: str,
    *,
    result_id: str,
    next_batch_index: int,
    batch_count: int,
    summary: dict[str, Any],
) -> None:
    """Upserts the resume point after one batch of ``run_batches`` completes
    (extract + pair + verify + reconcile + append all succeeded for it) —
    ``summary`` is the running ``ReconciliationSummary`` accumulated so far
    (see ``result_store.append_batch_result``), not just this batch's own."""
    with main_db() as conn:
        conn.execute(
            """INSERT INTO run_batch_checkpoint
               (graph_run_id, result_id, next_batch_index, batch_count, summary_json)
               VALUES (?,?,?,?,?)
               ON CONFLICT (graph_run_id) DO UPDATE SET
                   result_id = excluded.result_id,
                   next_batch_index = excluded.next_batch_index,
                   batch_count = excluded.batch_count,
                   summary_json = excluded.summary_json""",
            (graph_run_id, result_id, next_batch_index, batch_count, json.dumps(summary)),
        )


def record_batch_attempt(
    graph_run_id: str,
    *,
    batch_id: str,
    batch_index: int,
    supersedes_batch_id: str | None,
    status: str,
    error: str | None = None,
) -> None:
    """Audit trail for ONE batch ATTEMPT (success or hard failure) — distinct
    from :func:`save_run_batch_checkpoint`, which only ever tracks the single
    current resume position. Never upserted: every attempt (including a
    retried one, chained via ``supersedes_batch_id``) gets its own row, so a
    failed attempt's trail survives rather than being overwritten."""
    with main_db() as conn:
        conn.execute(
            """INSERT INTO run_batch_attempts
               (batch_id, run_id, batch_index, supersedes_batch_id, status, error, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                batch_id, graph_run_id, batch_index, supersedes_batch_id, status, error,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_latest_batch_attempt(graph_run_id: str, batch_index: int) -> dict[str, Any] | None:
    """The most recent attempt at this ``(graph_run_id, batch_index)`` — what
    a new attempt's ``supersedes_batch_id`` should point at, or ``None`` if
    this batch index has never been attempted before."""
    with main_db() as conn:
        row = conn.execute(
            """SELECT * FROM run_batch_attempts WHERE run_id = ? AND batch_index = ?
               ORDER BY created_at DESC LIMIT 1""",
            (graph_run_id, batch_index),
        ).fetchone()
    return dict(row) if row else None


def clear_run_batch_state(graph_run_id: str) -> None:
    """Drops the batch plan + checkpoint for this run — called once
    ``run_batches`` completes successfully (nothing left to resume) and when a
    fresh run starts."""
    with main_db() as conn:
        conn.execute("DELETE FROM run_batch_plan WHERE graph_run_id = ?", (graph_run_id,))
        conn.execute("DELETE FROM run_batch_checkpoint WHERE graph_run_id = ?", (graph_run_id,))


def has_run_batch_checkpoint(graph_run_id: str) -> bool:
    """True when this run has a resumable streaming-batch checkpoint — the
    signal the ``/retry`` route and the polled status use to decide whether a
    hard-failed ``run_batches`` step can resume from a batch."""
    with main_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM run_batch_checkpoint WHERE graph_run_id = ?", (graph_run_id,)
        ).fetchone()
    return row is not None


def has_batch_checkpoints(graph_run_id: str) -> bool:
    """True when at least one field pair has a resumable checkpoint — the
    signal the ``/retry`` route and the polled status use to decide whether a
    hard-failed ``pair_values`` step can resume from a batch, rather than
    only being retryable from scratch."""
    with main_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM pipeline_batch_checkpoints WHERE graph_run_id = ? LIMIT 1",
            (graph_run_id,),
        ).fetchone()
    return row is not None


def _row_to_dict(row) -> dict[str, Any]:
    batch_progress_json = row["batch_progress_json"] if "batch_progress_json" in row.keys() else None
    interrupt_json = row["interrupt_json"] if "interrupt_json" in row.keys() else None
    return {
        "graph_run_id": row["graph_run_id"],
        "status": row["status"],
        "current_step": row["current_step"],
        "step_timestamps": json.loads(row["step_timestamps_json"]),
        "failed_step": row["failed_step"],
        "error": row["error"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "created_at": row["created_at"],
        "batch_progress": json.loads(batch_progress_json) if batch_progress_json else None,
        "interrupt": json.loads(interrupt_json) if interrupt_json else None,
    }


def get(graph_run_id: str) -> dict[str, Any] | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_runs WHERE graph_run_id = ?", (graph_run_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None
