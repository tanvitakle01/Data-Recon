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
