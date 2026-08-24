"""Error-event log — one row per hard node failure across the Auto-mode
pipeline (see ``auto_pipeline/nodes.py``'s ``_run_step``, the wrapper every
one of the 7 wizard steps runs through). Append-only; never updated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.recon_engine import ids
from backend.recon_engine.storage.db import main_db


def record(*, run_id: str | None, batch_id: str | None, node: str, message: str) -> str:
    error_event_id = ids.new_id()
    with main_db() as conn:
        conn.execute(
            """INSERT INTO error_events (error_event_id, run_id, batch_id, node, message, created_at)
               VALUES (?,?,?,?,?,?)""",
            (error_event_id, run_id, batch_id, node, message, datetime.now(timezone.utc).isoformat()),
        )
    return error_event_id


def list_for_run(run_id: str) -> list[dict[str, Any]]:
    with main_db() as conn:
        rows = conn.execute(
            "SELECT * FROM error_events WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def _row_to_dict(row) -> dict[str, Any]:
    return dict(row)


def get(error_event_id: str) -> dict[str, Any] | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM error_events WHERE error_event_id = ?", (error_event_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


__all__ = ["record", "list_for_run", "get"]
