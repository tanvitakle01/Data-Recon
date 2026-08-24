"""Pending yes/no confirmation gate for a staged, not-yet-executed chat
action — currently only ``start_new_run`` (NEW_RUN while another run is
active). Intercepted BEFORE intent classification (see
``chat_assistant/orchestrator.py``): an unanswered, unexpired confirmation
means the next message is interpreted ONLY as an answer to it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.recon_engine import ids
from backend.recon_engine.storage.db import main_db

DEFAULT_TTL_SECONDS = 120


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stage(
    session_id: str,
    *,
    question: str,
    staged_action: dict[str, Any],
    target_run_ids: list[str],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Persists a new pending confirmation and returns its id. Does not check
    for (and does not need to guard against) an existing pending confirmation
    for this session — the orchestrator only ever calls this from the NEW_RUN
    branch, which is itself unreachable while ``get_pending`` still returns a
    live one (every message is routed to answer it first)."""
    confirmation_id = ids.new_id()
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(seconds=ttl_seconds)
    with main_db() as conn:
        conn.execute(
            """INSERT INTO chat_confirmations
               (confirmation_id, session_id, question, staged_action_json,
                target_run_ids_json, created_at, expires_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                confirmation_id, session_id, question, json.dumps(staged_action),
                json.dumps(target_run_ids), created_at.isoformat(), expires_at.isoformat(),
            ),
        )
    return confirmation_id


def get_pending(session_id: str) -> dict[str, Any] | None:
    """Returns ``None`` (nothing pending), ``{"status": "expired", ...}`` (a
    confirmation just lapsed and is surfaced exactly once here), or
    ``{"status": "pending", "confirmation_id", "question", "staged_action",
    "target_run_ids"}``.
    """
    with main_db() as conn:
        row = conn.execute(
            """SELECT * FROM chat_confirmations
               WHERE session_id = ? AND resolution IS NULL
               ORDER BY created_at DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
    if row is None:
        return None

    if row["expires_at"] < _now():
        with main_db() as conn:
            conn.execute(
                "UPDATE chat_confirmations SET resolution = 'expired', answered_at = ? "
                "WHERE confirmation_id = ?",
                (_now(), row["confirmation_id"]),
            )
        return {"status": "expired", "confirmation_id": row["confirmation_id"], "question": row["question"]}

    return {
        "status": "pending",
        "confirmation_id": row["confirmation_id"],
        "question": row["question"],
        "staged_action": json.loads(row["staged_action_json"]),
        "target_run_ids": json.loads(row["target_run_ids_json"]),
    }


def answer(confirmation_id: str, resolution: str) -> None:
    with main_db() as conn:
        conn.execute(
            "UPDATE chat_confirmations SET resolution = ?, answered_at = ? "
            "WHERE confirmation_id = ? AND resolution IS NULL",
            (resolution, _now(), confirmation_id),
        )


def clear_expired() -> int:
    """Bulk-expires every session's stale pending confirmation — called from
    the watchdog tick so a session that never sends another message still
    doesn't have a live confirmation sitting forever. Returns the count
    cleared."""
    with main_db() as conn:
        cur = conn.execute(
            "UPDATE chat_confirmations SET resolution = 'expired', answered_at = ? "
            "WHERE resolution IS NULL AND expires_at < ?",
            (_now(), _now()),
        )
        return cur.rowcount
