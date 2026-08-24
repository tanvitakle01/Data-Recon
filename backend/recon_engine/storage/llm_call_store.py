"""LLM-call log — one row per ``FailoverLLMClient.complete_json`` invocation
(the single funnel every LLM call in the codebase goes through: value
pairing, contract compilation, candidate-key identification). Append-only;
never updated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.recon_engine import ids
from backend.recon_engine.storage.db import main_db


def record(
    *,
    run_id: str | None,
    batch_id: str | None,
    node: str | None,
    preferred: str,
    provider_used: str | None,
    fallback_occurred: bool,
    all_failed: bool,
) -> str:
    llm_call_id = ids.new_id()
    with main_db() as conn:
        conn.execute(
            """INSERT INTO llm_calls
               (llm_call_id, run_id, batch_id, node, preferred, provider_used,
                fallback_occurred, all_failed, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                llm_call_id, run_id, batch_id, node, preferred, provider_used,
                int(fallback_occurred), int(all_failed), datetime.now(timezone.utc).isoformat(),
            ),
        )
    return llm_call_id


def list_for_run(run_id: str) -> list[dict[str, Any]]:
    with main_db() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_calls WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall()
    return [dict(r) for r in rows]


__all__ = ["record", "list_for_run"]
