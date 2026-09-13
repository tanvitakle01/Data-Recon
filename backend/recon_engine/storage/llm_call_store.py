"""LLM-call log (in-memory) — one row per ``FailoverLLMClient.complete_json``
invocation (the single funnel every LLM call in the codebase goes through:
value pairing, contract compilation, candidate-key identification).
Append-only; never updated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.recon_engine import ids

_CALLS: dict[str, dict[str, Any]] = {}


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
    _CALLS[llm_call_id] = {
        "llm_call_id": llm_call_id,
        "run_id": run_id,
        "batch_id": batch_id,
        "node": node,
        "preferred": preferred,
        "provider_used": provider_used,
        "fallback_occurred": fallback_occurred,
        "all_failed": all_failed,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return llm_call_id


def list_for_run(run_id: str) -> list[dict[str, Any]]:
    rows = [r for r in _CALLS.values() if r["run_id"] == run_id]
    return sorted(rows, key=lambda r: r["created_at"])


__all__ = ["record", "list_for_run"]
