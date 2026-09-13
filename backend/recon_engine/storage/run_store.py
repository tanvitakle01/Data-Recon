"""Reconciliation run store (in-memory)."""

from __future__ import annotations

import uuid

from backend.recon_engine.models.run import ReconciliationRun

_RUNS: dict[str, ReconciliationRun] = {}


def new_run_id() -> str:
    return "run_" + uuid.uuid4().hex


def save_run(run: ReconciliationRun) -> ReconciliationRun:
    _RUNS[run.run_id] = run
    return run


def update_run(run: ReconciliationRun) -> ReconciliationRun:
    _RUNS[run.run_id] = run
    return run


def get_run(run_id: str) -> ReconciliationRun | None:
    return _RUNS.get(run_id)


def list_runs() -> list[ReconciliationRun]:
    return sorted(_RUNS.values(), key=lambda r: r.created_at, reverse=True)
