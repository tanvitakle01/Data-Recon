"""Value-pair library store (relational, exact-lookup).

Mirrors ``attribute_mapping_store.py``'s conventions: a plain relational table,
dedup enforced by a UNIQUE constraint on the canonical composite key
``(source_connector, target_connector, source_field, target_field,
source_value, target_value)``.

Conflict policy differs deliberately from the attribute-mapping library:
:func:`propose` never overwrites an existing row. Once a pair has been
proposed, a later pipeline run proposing the same source value returns the
existing row unchanged.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.recon_engine.models.value_pair import ValuePair
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
        evidence=json.loads(row["evidence_json"]),
        added_by=row["added_by"],
        added_on=datetime.fromisoformat(row["added_on"]),
        version=row["version"],
    )


def get(pair_id: str) -> ValuePair | None:
    with main_db() as conn:
        row = conn.execute("SELECT * FROM value_pair_library WHERE id = ?", (pair_id,)).fetchone()
    return _row_to_pair(row) if row else None


def lookup_pairs(
    *, source_connector: str, target_connector: str, source_field: str, target_field: str
) -> dict[str, ValuePair]:
    """Every stored pair for this field pair, keyed by ``source_value``.

    The pipeline's library-first step: a hit here resolves a residual value
    immediately — no LLM call, no re-verification (it was verified once at
    proposal time).
    """
    with main_db() as conn:
        rows = conn.execute(
            """SELECT * FROM value_pair_library
               WHERE source_connector = ? AND target_connector = ?
                 AND source_field = ? AND target_field = ?""",
            (source_connector, target_connector, source_field, target_field),
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
    """Persist a freshly-verified pairing (an ordered ops chain).

    If a row already exists for this exact ``(..., source_value,
    target_value)`` key, it is returned unchanged — see the module docstring
    on conflict policy. ``target_value`` is part of the lookup key so a
    genuinely different target proposed for the same source value inserts its
    OWN row instead of being handed back an unrelated target's row (one-to-many
    support).
    """
    evidence = evidence or {}
    with main_db() as conn:
        existing = conn.execute(
            """SELECT * FROM value_pair_library
               WHERE source_connector = ? AND target_connector = ?
                 AND source_field = ? AND target_field = ?
                 AND source_value = ? AND target_value = ?""",
            (source_connector, target_connector, source_field, target_field,
             source_value, target_value),
        ).fetchone()
        if existing:
            return _row_to_pair(existing)

        pair_id = new_id()
        now = _utcnow()
        conn.execute(
            """INSERT INTO value_pair_library
               (id, source_connector, target_connector, source_field, target_field,
                source_value, target_value, ops_json, evidence_json,
                added_by, added_on, version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pair_id, source_connector, target_connector, source_field, target_field,
                source_value, target_value, json.dumps(ops),
                json.dumps(evidence), added_by, now.isoformat(), 1,
            ),
        )

    got = get(pair_id)
    assert got is not None  # just written
    return got


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
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with main_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM value_pair_library {where} ORDER BY added_on DESC", params
        ).fetchall()
    return [_row_to_pair(r) for r in rows]
