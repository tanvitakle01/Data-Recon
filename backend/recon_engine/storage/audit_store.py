"""Append-only audit log store."""

from __future__ import annotations

import json
import uuid

from backend.recon_engine.models.audit import AuditAction, AuditEvent
from backend.recon_engine.storage.db import main_db


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
    with main_db() as conn:
        conn.execute(
            """INSERT INTO audit_log
               (event_id, timestamp, actor, action, entity_type, entity_id, details_json)
               VALUES (?,?,?,?,?,?,?)""",
            (
                event.event_id, event.timestamp.isoformat(), event.actor, event.action.value,
                event.entity_type, event.entity_id, json.dumps(event.details),
            ),
        )
    return event


def _row_to_event(row) -> AuditEvent:
    return AuditEvent(
        event_id=row["event_id"],
        timestamp=row["timestamp"],
        actor=row["actor"],
        action=AuditAction(row["action"]),
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        details=json.loads(row["details_json"]),
    )


def list_events(entity_id: str | None = None) -> list[AuditEvent]:
    with main_db() as conn:
        if entity_id is None:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY timestamp DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE entity_id = ? ORDER BY timestamp DESC",
                (entity_id,),
            ).fetchall()
    return [_row_to_event(r) for r in rows]
