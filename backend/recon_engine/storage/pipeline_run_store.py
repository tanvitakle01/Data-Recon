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
    """Inserts the row in ``CREATED`` — the caller (``start_auto_run_state``)
    immediately follows with ``run_registry.transition(..., RUNNING, ...)``.
    Never inserts any other status here: this module has no ``status``-writing
    function left besides this literal, fixed initial value — see
    ``run_registry.transition``, the sole place ``pipeline_runs.status``
    changes after creation."""
    with main_db() as conn:
        conn.execute(
            """INSERT INTO pipeline_runs
               (graph_run_id, status, current_step, step_timestamps_json,
                failed_step, error, result_json, created_at, batch_progress_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                graph_run_id, "created", None, json.dumps({}),
                None, None, None, datetime.now(timezone.utc).isoformat(), None,
            ),
        )


def update_progress(
    graph_run_id: str,
    *,
    current_step: str | None = None,
    step_timestamps: dict[str, Any] | None = None,
    failed_step: str | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
    interrupt: dict[str, Any] | None = None,
) -> None:
    """Everything about a run EXCEPT its lifecycle status — deliberately has
    no ``status`` parameter at all, so a status change cannot happen through
    this function; see ``run_registry.transition`` for that.

    ``interrupt`` carries the resolver bot's pending question while paused —
    callers pass ``None`` explicitly to clear a stale one whenever the run
    isn't actually paused (see ``routes/auto_pipeline.py``), never left as a
    leftover default.
    """
    with main_db() as conn:
        conn.execute(
            """UPDATE pipeline_runs
               SET current_step = ?, step_timestamps_json = ?,
                   failed_step = ?, error = ?, result_json = ?, interrupt_json = ?
               WHERE graph_run_id = ?""",
            (
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
    stage: str,
    batches_completed: int,
) -> None:
    """Live per-batch progress for the currently-running ``run_batches`` node
    (see ``auto_pipeline.nodes._report_batch_stage``) — a separate write from
    :func:`update_progress` (which only runs once per WHOLE graph node
    completes) so the polling status endpoint can show "batch N of M" plus
    which sub-stage of that batch (fetching source, fetching target, pairing
    values, reconciling, completed) is in flight while ``run_batches`` is
    still mid-flight. ``stage`` values are consumed verbatim by the
    frontend's per-batch checklist — keep the two in sync if either changes.
    ``batches_completed`` is the count of FULLY finished batches (not
    ``batch_index``, which is the batch currently being worked on) — the
    number the frontend shows as "N/M batches done".
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
                        "stage": stage,
                        "batches_completed": batches_completed,
                    }
                ),
                graph_run_id,
            ),
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


# ── suspended-run ("Stored Runs") support ───────────────────────────────────

def save_suspension(
    graph_run_id: str,
    *,
    user_name: str | None,
    suspend_reason: str,
    data_fingerprint: dict[str, Any],
    expires_at: str,
) -> None:
    """Upserts the ``pipeline_run_suspensions`` row for a run entering
    SUSPENDING — written eagerly at the moment suspend is REQUESTED (not once
    it actually takes effect a batch later), so the Stored Runs tab can show
    "suspending…" immediately and ``data_fingerprint`` is captured against the
    state the user actually asked to pause, not whatever batch happens to be
    running when the cooperative checkpoint fires.
    """
    with main_db() as conn:
        conn.execute(
            """INSERT INTO pipeline_run_suspensions
               (graph_run_id, user_name, suspended_at, suspend_reason,
                data_fingerprint_json, expires_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT (graph_run_id) DO UPDATE SET
                   user_name = excluded.user_name,
                   suspended_at = excluded.suspended_at,
                   suspend_reason = excluded.suspend_reason,
                   data_fingerprint_json = excluded.data_fingerprint_json,
                   expires_at = excluded.expires_at""",
            (
                graph_run_id, user_name, datetime.now(timezone.utc).isoformat(),
                suspend_reason, json.dumps(data_fingerprint), expires_at,
            ),
        )


def set_suspension_name(graph_run_id: str, name: str) -> None:
    """Renames an existing suspension row — used by the chat orchestrator's
    post-suspend naming follow-up, answered a turn after ``save_suspension``
    already wrote the row with its auto-generated default name. A no-op if
    the suspension is already gone (resumed/discarded/expired before the
    user answered)."""
    with main_db() as conn:
        conn.execute(
            "UPDATE pipeline_run_suspensions SET user_name = ? WHERE graph_run_id = ?",
            (name, graph_run_id),
        )


def get_suspension(graph_run_id: str) -> dict[str, Any] | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_run_suspensions WHERE graph_run_id = ?", (graph_run_id,)
        ).fetchone()
    if row is None:
        return None
    return {
        "graph_run_id": row["graph_run_id"],
        "user_name": row["user_name"],
        "suspended_at": row["suspended_at"],
        "suspend_reason": row["suspend_reason"],
        "data_fingerprint": json.loads(row["data_fingerprint_json"]),
        "expires_at": row["expires_at"],
    }


def list_suspensions() -> list[dict[str, Any]]:
    """Every row in ``pipeline_run_suspensions`` — the Stored Runs tab further
    joins each against :func:`get`/:func:`get_run_batch_checkpoint`/
    :func:`get_run_batch_plan` for live status/progress; this store makes no
    assumption about which of those a caller actually needs."""
    with main_db() as conn:
        rows = conn.execute(
            "SELECT graph_run_id FROM pipeline_run_suspensions ORDER BY suspended_at DESC"
        ).fetchall()
    return [get_suspension(row["graph_run_id"]) for row in rows]


def delete_suspension(graph_run_id: str) -> None:
    with main_db() as conn:
        conn.execute("DELETE FROM pipeline_run_suspensions WHERE graph_run_id = ?", (graph_run_id,))


def list_expired_suspensions(*, as_of: str | None = None) -> list[str]:
    """graph_run_ids whose suspension has passed ``expires_at`` — the
    watchdog's expiry sweep reads this, then transitions each to CANCELLED and
    calls :func:`cleanup_run_artifacts`, same as an explicit delete."""
    cutoff = as_of or datetime.now(timezone.utc).isoformat()
    with main_db() as conn:
        rows = conn.execute(
            "SELECT graph_run_id FROM pipeline_run_suspensions WHERE expires_at < ?", (cutoff,)
        ).fetchall()
    return [row["graph_run_id"] for row in rows]


def cleanup_run_artifacts(graph_run_id: str) -> None:
    """Drops every run-scoped artifact that has no reason to survive past a
    run's CANCELLED/expired-SUSPENDED endpoint: the batch plan/checkpoint
    (:func:`clear_run_batch_state`), corroboration evidence
    (``corroboration_store.clear``), and any suspension record
    (:func:`delete_suspension`).

    Shared by three callers: an explicit Stored-Runs delete, the expiry
    watchdog, and the CANCELLING -> CANCELLED path — the last of which used to
    leak all three of these (only a successful ``finalize()`` ever cleaned
    them up before). Deliberately never touches `results`/`run_batch_checkpoint
    .result_id`'s underlying result row — partial results must remain
    inspectable after a run is gone, same as a completed run's results do.
    """
    # Local import — avoids a module-level circular import (corroboration_store
    # does not import pipeline_run_store, but keeping this import next to its
    # single call site makes the dependency explicit here).
    from backend.recon_engine.storage import corroboration_store

    clear_run_batch_state(graph_run_id)
    corroboration_store.clear(graph_run_id)
    delete_suspension(graph_run_id)
