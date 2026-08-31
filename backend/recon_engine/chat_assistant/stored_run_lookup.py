"""Resolves a chat "resume <identifier>" request (see
``intent.parse_resume_stored_query``) against stored (SUSPENDED) runs by
exact name, exact/substring run_id, or a relative time reference against
``suspended_at``. Never guesses a single "best" match on its own — the
orchestrator must list every candidate this returns and ask the user to pick
when there's more than one; a single match is resumed outright.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.recon_engine.run_registry import RunState
from backend.recon_engine.storage import pipeline_run_store

_TIME_PHRASES: dict[str, timedelta] = {
    "this morning": timedelta(hours=12),
    "this afternoon": timedelta(hours=12),
    "this evening": timedelta(hours=12),
    "today": timedelta(hours=24),
    "yesterday": timedelta(hours=48),
    "last hour": timedelta(hours=1),
    "an hour ago": timedelta(hours=1),
    "this week": timedelta(days=7),
    "last week": timedelta(days=14),
}

_RELATIVE_AGO = re.compile(r"(\d+)\s*(minute|hour|day)s?\s*ago")
_UNIT_TO_DELTA = {"minute": timedelta(minutes=1), "hour": timedelta(hours=1), "day": timedelta(days=1)}


def _parse_time_reference(query: str) -> timedelta | None:
    text = query.strip().lower()
    match = _RELATIVE_AGO.search(text)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        return _UNIT_TO_DELTA[unit] * amount
    for phrase, window in _TIME_PHRASES.items():
        if phrase in text:
            return window
    return None


def _stored_candidates(*, any_status: bool = False) -> list[dict[str, Any]]:
    """Every suspension row this run is tracked by — restricted to owning runs
    still actually SUSPENDED by default (mirrors the resume path's
    requirement that there's something to resume), or every tracked run
    regardless of current status when ``any_status`` is set (used by chat's
    STATUS fallback — a run resumed from the Stored Runs tab stays tracked
    there through RUNNING/COMPLETED/FAILED, see ``routes.auto_pipeline.
    list_stored_runs``)."""
    out = []
    for suspension in pipeline_run_store.list_suspensions():
        run = pipeline_run_store.get(suspension["graph_run_id"])
        if run is None:
            continue
        if any_status or run.get("status") == RunState.SUSPENDED.value:
            out.append(suspension)
    return out


def find(query: str, *, any_status: bool = False) -> list[dict[str, Any]]:
    """Returns every stored run matching ``query``, trying exact name/run_id
    first, then substring, then a time reference against ``suspended_at`` —
    the first tier to produce any match wins (never mixes tiers). An empty
    list means no match at all; a list of length > 1 at any tier means the
    caller must disambiguate rather than pick one.

    ``any_status=False`` (default) — the resume path's behavior, unchanged —
    only matches runs still actually SUSPENDED. Pass ``any_status=True`` to
    also match a tracked run that has since resumed/completed/failed (chat's
    STATUS-by-name fallback only)."""
    text = query.strip()
    if not text:
        return []
    candidates = _stored_candidates(any_status=any_status)
    lowered = text.lower()

    exact = [
        c for c in candidates
        if c["graph_run_id"].lower() == lowered or (c["user_name"] or "").strip().lower() == lowered
    ]
    if exact:
        return exact

    substring = [
        c for c in candidates
        if lowered in c["graph_run_id"].lower() or lowered in (c["user_name"] or "").strip().lower()
    ]
    if substring:
        return substring

    window = _parse_time_reference(text)
    if window is None:
        return []
    now = datetime.now(timezone.utc)
    return [c for c in candidates if now - datetime.fromisoformat(c["suspended_at"]) <= window]
