"""Reconciliation result classifications and summary."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecordClass(str, Enum):
    """The five terminal classifications after the full outer join."""

    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING_IN_SOURCE = "missing_in_source"
    MISSING_IN_TARGET = "missing_in_target"
    EXCEPTION = "exception"


class ReconciliationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = 0
    match: int = 0
    mismatch: int = 0
    missing_in_source: int = 0
    missing_in_target: int = 0
    exception: int = 0

    @classmethod
    def from_counts(cls, counts: dict[str, int]) -> "ReconciliationSummary":
        return cls(
            match=counts.get(RecordClass.MATCH.value, 0),
            mismatch=counts.get(RecordClass.MISMATCH.value, 0),
            missing_in_source=counts.get(RecordClass.MISSING_IN_SOURCE.value, 0),
            missing_in_target=counts.get(RecordClass.MISSING_IN_TARGET.value, 0),
            exception=counts.get(RecordClass.EXCEPTION.value, 0),
            total=sum(counts.values()),
        )


class ReconciliationResult(BaseModel):
    """Persisted outcome of a run. Detail rows live on disk at ``storage_path``."""

    model_config = ConfigDict(extra="forbid")

    result_id: str
    run_id: str
    contract_id: str
    contract_version: int

    summary: ReconciliationSummary
    storage_path: str
    created_at: datetime = Field(default_factory=_utcnow)
