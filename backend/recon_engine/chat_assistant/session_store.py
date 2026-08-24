"""Per-chat-session run binding — keyed by the EXISTING authenticated session
id (``backend.auth.sessions.SessionInfo.session_id``), never a new cookie.

Cancel-and-replace concurrency model: a session has at most one run it
considers active at a time (``active_run_id``). ``NEW_RUN`` while this is set
to an active (non-terminal) run raises a confirmation instead of silently
starting a second run — see ``chat_assistant/orchestrator.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.recon_engine.storage.db import main_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_active_run(session_id: str) -> str | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT active_run_id FROM chat_run_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return row["active_run_id"] if row else None


def set_active_run(session_id: str, run_id: str | None) -> None:
    with main_db() as conn:
        conn.execute(
            """INSERT INTO chat_run_sessions (session_id, active_run_id, updated_at)
               VALUES (?,?,?)
               ON CONFLICT (session_id) DO UPDATE SET
                   active_run_id = excluded.active_run_id,
                   updated_at = excluded.updated_at""",
            (session_id, run_id, _now()),
        )


def clear_active_run_if(session_id: str, run_id: str) -> None:
    """Clears ``active_run_id`` only if it still equals ``run_id`` — used by
    the orphan sweep so it never clobbers a DIFFERENT run the session may have
    started since (e.g. it already replaced the orphaned one before boot)."""
    with main_db() as conn:
        conn.execute(
            """UPDATE chat_run_sessions SET active_run_id = NULL, updated_at = ?
               WHERE session_id = ? AND active_run_id = ?""",
            (_now(), session_id, run_id),
        )


def sessions_bound_to(run_id: str) -> list[str]:
    with main_db() as conn:
        rows = conn.execute(
            "SELECT session_id FROM chat_run_sessions WHERE active_run_id = ?", (run_id,)
        ).fetchall()
    return [row["session_id"] for row in rows]
