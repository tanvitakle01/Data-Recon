"""Models for the script-transformation (preview + approval) flow.

The user approves transformed DATA, never code. The script is an internal
artifact pinned by ``script_hash``: the approval records the hash of the exact
script that produced the approved preview, and production execution refuses to
run anything whose hash differs.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def script_sha256(script_text: str) -> str:
    return hashlib.sha256(script_text.encode("utf-8")).hexdigest()


class GeneratedBy(str, Enum):
    GROQ = "groq"
    OPENAI = "openai"
    FALLBACK = "fallback"


class TransformationScript(BaseModel):
    """A generated transformation script + provenance.

    ``script`` must define ``transform(df)`` (pandas in, pandas out). It is
    only ever executed after static validation, inside the restricted sandbox
    namespace, and in production only when a data approval pins its hash.
    """

    model_config = ConfigDict(extra="forbid")

    script_id: str
    generated_by: GeneratedBy
    generated_at: datetime = Field(default_factory=_utcnow)
    explanation: list[str] = Field(default_factory=list)
    script: str
    script_hash: str
    source_columns: list[str] = Field(default_factory=list)
    target_columns: list[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    created_by: str = "system"

    def public_dict(self) -> dict[str, Any]:
        """API-facing shape: everything except the script text itself."""
        data = self.model_dump(mode="json")
        data.pop("script")
        return data


class PreviewStatus(str, Enum):
    PENDING = "pending"  # awaiting user decision
    APPROVED = "approved"
    REJECTED = "rejected"


class ScriptPreview(BaseModel):
    """A stored sandbox-execution snapshot: the data the user reviews."""

    model_config = ConfigDict(extra="forbid")

    preview_id: str
    script_id: str
    script_hash: str
    row_count: int
    affected_rows: int
    modified_columns: list[dict[str, Any]] = Field(default_factory=list)
    row_diffs: list[dict[str, Any]] = Field(default_factory=list)
    execution_log: list[str] = Field(default_factory=list)
    storage_path: str
    status: PreviewStatus = PreviewStatus.PENDING
    created_at: datetime = Field(default_factory=_utcnow)
    created_by: str = "system"


class ScriptApproval(BaseModel):
    """User sign-off on a preview snapshot (data-centric approval)."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str
    preview_snapshot_id: str
    script_id: str
    script_hash: str
    approved_by: str
    approved_at: datetime = Field(default_factory=_utcnow)
