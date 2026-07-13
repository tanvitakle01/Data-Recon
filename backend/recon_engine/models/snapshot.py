"""Immutable raw-layer snapshot metadata.

Every upload or API extract creates a new, append-only snapshot. Snapshots are
never modified. The engine only ever *reads* them; all transformation happens
in a derived Shadow_Source.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RawLayer(str, Enum):
    SOURCE = "Raw_Source"
    TARGET = "Raw_Target"


class RawSnapshot(BaseModel):
    """Metadata for one immutable raw dataset snapshot.

    The actual row data is stored separately on disk (parquet) at
    ``storage_path``; this record is the lineage/index entry.
    """

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    layer: RawLayer
    source_type: str = Field(..., description="e.g. 'excel', 's4', 'ibp'.")
    comparison_type: str | None = None

    snapshot_hash: str = Field(..., description="SHA-256 of the canonical row payload.")
    row_count: int
    columns: list[str]

    created_at: datetime = Field(default_factory=_utcnow)
    created_by: str = "system"

    # Where the immutable payload lives and any extra provenance
    # (original filename, connector entity set, request id, etc.).
    storage_path: str
    lineage: dict[str, Any] = Field(default_factory=dict)
