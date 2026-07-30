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
                failed_step, error, result_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                graph_run_id, "running", None, json.dumps({}),
                None, None, None, datetime.now(timezone.utc).isoformat(),
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
) -> None:
    with main_db() as conn:
        conn.execute(
            """UPDATE pipeline_runs
               SET status = ?, current_step = ?, step_timestamps_json = ?,
                   failed_step = ?, error = ?, result_json = ?
               WHERE graph_run_id = ?""",
            (
                status,
                current_step,
                json.dumps(step_timestamps or {}),
                failed_step,
                error,
                json.dumps(result) if result is not None else None,
                graph_run_id,
            ),
        )


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "graph_run_id": row["graph_run_id"],
        "status": row["status"],
        "current_step": row["current_step"],
        "step_timestamps": json.loads(row["step_timestamps_json"]),
        "failed_step": row["failed_step"],
        "error": row["error"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "created_at": row["created_at"],
    }


def get(graph_run_id: str) -> dict[str, Any] | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_runs WHERE graph_run_id = ?", (graph_run_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None
