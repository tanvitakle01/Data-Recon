"""Audit log events for a fully auditable, reproducible workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditAction(str, Enum):
    SNAPSHOT_CREATED = "snapshot_created"
    CONTRACT_DRAFTED = "contract_drafted"
    CONTRACT_VALIDATED = "contract_validated"
    CONTRACT_VALIDATION_FAILED = "contract_validation_failed"
    CONTRACT_APPROVED = "contract_approved"
    CONTRACT_REJECTED = "contract_rejected"
    RUN_STARTED = "run_started"
    SHADOW_CREATED = "shadow_created"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    SHADOW_EXPIRED = "shadow_expired"
    # Script-transformation (preview + approval) flow
    SCRIPT_GENERATED = "script_generated"
    SCRIPT_REJECTED = "script_rejected"
    PREVIEW_CREATED = "preview_created"
    PREVIEW_APPROVED = "preview_approved"
    PREVIEW_REJECTED = "preview_rejected"
    # Attribute-mapping library
    LIBRARY_MAPPING_STORED = "library_mapping_stored"
    LIBRARY_MAPPING_DELETED = "library_mapping_deleted"
    LIBRARY_FLUSHED = "library_flushed"


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    timestamp: datetime = Field(default_factory=_utcnow)
    actor: str = "system"
    action: AuditAction
    entity_type: str = Field(..., description="e.g. 'snapshot', 'contract', 'run'.")
    entity_id: str
    details: dict[str, Any] = Field(default_factory=dict)
