"""Append-only audit log store (in-memory)."""

from __future__ import annotations

import uuid

from backend.recon_engine.models.audit import AuditAction, AuditEvent

_EVENTS: dict[str, AuditEvent] = {}


def record(
    action: AuditAction,
    *,
    entity_type: str,
    entity_id: str,
    actor: str = "system",
    details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_id="evt_" + uuid.uuid4().hex,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    )
    _EVENTS[event.event_id] = event
    return event


def list_events(entity_id: str | None = None) -> list[AuditEvent]:
    values = sorted(_EVENTS.values(), key=lambda e: e.timestamp, reverse=True)
    if entity_id is not None:
        values = [e for e in values if e.entity_id == entity_id]
    return values
