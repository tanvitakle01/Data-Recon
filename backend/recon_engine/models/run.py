"""Reconciliation run and Shadow_Source metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ShadowSource(BaseModel):
    """A derived, disposable dataset produced by applying an approved contract
    to a Raw_Source snapshot.

    A Shadow_Source is fully reproducible from ``raw_snapshot_hash`` +
    ``contract_id``/``contract_version``. It is stored under the ``recon_shadow``
    schema (a separate SQLite DB) and expires at ``expires_at`` (TTL cleanup).
    Raw_Source is never modified to create it.
    """

    model_config = ConfigDict(extra="forbid")

    shadow_id: str
    run_id: str
    contract_id: str
    contract_version: int

    raw_snapshot_id: str
    raw_snapshot_hash: str

    row_count: int
    storage_path: str

    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime


class ReconciliationRun(BaseModel):
    """One execution of an approved contract against a source/target pair."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    contract_id: str
    contract_version: int

    source_snapshot_id: str
    target_snapshot_id: str
    shadow_id: str | None = None

    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=_utcnow)
    created_by: str = "system"
    error: str | None = None
