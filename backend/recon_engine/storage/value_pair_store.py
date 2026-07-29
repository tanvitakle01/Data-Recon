"""Value-pair library store (relational, exact-lookup).

Mirrors ``attribute_mapping_store.py``'s conventions: a plain relational table,
dedup enforced by a UNIQUE constraint on the canonical composite key
``(source_connector, target_connector, source_field, target_field,
source_value)``.

Conflict policy differs deliberately from the attribute-mapping library:
:func:`propose` never overwrites an existing row. Once a pair has been
proposed (and especially once a human has APPROVED or REJECTED it), a later
pipeline run proposing the same source value returns the existing row
unchanged — a human decision is never silently clobbered.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.recon_engine.models.value_pair import ValuePair, ValuePairStatus
from backend.recon_engine.storage.db import main_db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return "valpair_" + uuid.uuid4().hex


def _row_to_pair(row) -> ValuePair:
    return ValuePair(
        id=row["id"],
        source_connector=row["source_connector"],
        target_connector=row["target_connector"],
        source_field=row["source_field"],
        target_field=row["target_field"],
        source_value=row["source_value"],
        target_value=row["target_value"],
        ops=json.loads(row["ops_json"]),
        status=ValuePairStatus(row["status"]),
        evidence=json.loads(row["evidence_json"]),
        added_by=row["added_by"],
        added_on=datetime.fromisoformat(row["added_on"]),
        reviewed_by=row["reviewed_by"],
        reviewed_on=datetime.fromisoformat(row["reviewed_on"]) if row["reviewed_on"] else None,
        version=row["version"],
    )


def get(pair_id: str) -> ValuePair | None:
    with main_db() as conn:
        row = conn.execute("SELECT * FROM value_pair_library WHERE id = ?", (pair_id,)).fetchone()
    return _row_to_pair(row) if row else None


def lookup_approved(
    *, source_connector: str, target_connector: str, source_field: str, target_field: str
) -> dict[str, ValuePair]:
    """All APPROVED rows for this field pair, keyed by ``source_value``.

    The pipeline's library-first step: a hit here resolves a residual value
    immediately — no LLM call, no re-verification (it was verified once at
    proposal time, and a human has since approved it for reuse).
    """
    with main_db() as conn:
        rows = conn.execute(
            """SELECT * FROM value_pair_library
               WHERE source_connector = ? AND target_connector = ?
                 AND source_field = ? AND target_field = ? AND status = ?""",
            (source_connector, target_connector, source_field, target_field, ValuePairStatus.APPROVED.value),
        ).fetchall()
    return {row["source_value"]: _row_to_pair(row) for row in rows}


def propose(
    *,
    source_connector: str,
    target_connector: str,
    source_field: str,
    target_field: str,
    source_value: str,
    target_value: str,
    ops: list[dict[str, Any]],
    evidence: dict[str, Any] | None = None,
    added_by: str = "system",
) -> ValuePair:
    """Insert a PENDING row for a freshly-verified pairing (an ordered ops chain).

    If a row already exists for this key (any status), it is returned
    unchanged — see the module docstring on conflict policy.
    """
    evidence = evidence or {}
    with main_db() as conn:
        existing = conn.execute(
            """SELECT * FROM value_pair_library
               WHERE source_connector = ? AND target_connector = ?
                 AND source_field = ? AND target_field = ? AND source_value = ?""",
            (source_connector, target_connector, source_field, target_field, source_value),
        ).fetchone()
        if existing:
            return _row_to_pair(existing)

        pair_id = new_id()
        now = _utcnow()
        conn.execute(
            """INSERT INTO value_pair_library
               (id, source_connector, target_connector, source_field, target_field,
                source_value, target_value, ops_json, status, evidence_json,
                added_by, added_on, reviewed_by, reviewed_on, version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pair_id, source_connector, target_connector, source_field, target_field,
                source_value, target_value, json.dumps(ops), ValuePairStatus.PENDING.value,
                json.dumps(evidence), added_by, now.isoformat(), None, None, 1,
            ),
        )

    got = get(pair_id)
    assert got is not None  # just written
    return got


def _set_status(pair_id: str, status: ValuePairStatus, *, actor: str) -> ValuePair | None:
    now = _utcnow()
    with main_db() as conn:
        cur = conn.execute(
            """UPDATE value_pair_library
               SET status = ?, reviewed_by = ?, reviewed_on = ?, version = version + 1
               WHERE id = ?""",
            (status.value, actor, now.isoformat(), pair_id),
        )
        if cur.rowcount == 0:
            return None
    return get(pair_id)


def approve(pair_id: str, *, actor: str = "system") -> ValuePair | None:
    return _set_status(pair_id, ValuePairStatus.APPROVED, actor=actor)


def reject(pair_id: str, *, actor: str = "system", reason: str | None = None) -> ValuePair | None:
    if reason:
        existing = get(pair_id)
        if existing is None:
            return None
        evidence = dict(existing.evidence)
        evidence["rejection_reason"] = reason
        with main_db() as conn:
            conn.execute(
                "UPDATE value_pair_library SET evidence_json = ? WHERE id = ?",
                (json.dumps(evidence), pair_id),
            )
    return _set_status(pair_id, ValuePairStatus.REJECTED, actor=actor)


def delete(pair_id: str) -> bool:
    with main_db() as conn:
        cur = conn.execute("DELETE FROM value_pair_library WHERE id = ?", (pair_id,))
        return cur.rowcount > 0


def flush() -> int:
    """Empty the whole value-pair library (demo cold-start). Returns rows removed."""
    with main_db() as conn:
        cur = conn.execute("DELETE FROM value_pair_library")
        return cur.rowcount


def list_pairs(
    *,
    source_connector: str | None = None,
    target_connector: str | None = None,
    status: ValuePairStatus | None = None,
) -> list[ValuePair]:
    """Browsable/filterable listing for the Library tab (most-recent first)."""
    clauses: list[str] = []
    params: list[str] = []
    if source_connector:
        clauses.append("source_connector = ?")
        params.append(source_connector)
    if target_connector:
        clauses.append("target_connector = ?")
        params.append(target_connector)
    if status:
        clauses.append("status = ?")
        params.append(status.value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with main_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM value_pair_library {where} ORDER BY added_on DESC", params
        ).fetchall()
    return [_row_to_pair(r) for r in rows]
