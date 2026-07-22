"""Attribute-mapping library store (relational, exact-lookup).

Reuse here is an EXACT-lookup problem — "are these specific source+target
columns present? fetch that validated row" — not a similarity problem, so this
is a plain relational table, not a vector index. Dedup is enforced by a UNIQUE
constraint on the canonical composite key
``(source_connector, target_connector, comparison_type,
source_columns_key, target_columns_key)``.

Conflict policy (confirmed): OVERWRITE + bump ``version`` on store-back — one
canonical row per key, ``last_used_on`` / ``validated_by_run_id`` refreshed.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from backend.recon_engine.canonical import canonical_column_key
from backend.recon_engine.models.attribute_mapping import (
    AttributeMapping,
    AttributePair,
    MappingProvenance,
)
from backend.recon_engine.storage.db import main_db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return "attrmap_" + uuid.uuid4().hex


def _row_to_mapping(row) -> AttributeMapping:
    return AttributeMapping(
        id=row["id"],
        source_connector=row["source_connector"],
        target_connector=row["target_connector"],
        comparison_type=row["comparison_type"],
        source_columns_key=row["source_columns_key"],
        target_columns_key=row["target_columns_key"],
        mappings=[AttributePair.model_validate(m) for m in json.loads(row["mappings_json"])],
        provenance=MappingProvenance(row["provenance"]),
        confidence=row["confidence"],
        added_by=row["added_by"],
        added_on=datetime.fromisoformat(row["added_on"]),
        last_used_on=datetime.fromisoformat(row["last_used_on"]) if row["last_used_on"] else None,
        validated_by_run_id=row["validated_by_run_id"],
        version=row["version"],
        details=json.loads(row["details_json"]),
    )


def lookup(
    *,
    source_connector: str,
    target_connector: str,
    comparison_type: str,
    source_columns: list[str],
    target_columns: list[str],
) -> AttributeMapping | None:
    """Find a stored mapping for this exact source+target column set.

    Computes the canonical keys with the SAME shared function store-back uses,
    so an identical column set (in any order) resolves to the same row. Pure
    read — the caller calls :func:`touch_last_used` on a genuine hit.
    """
    src_key = canonical_column_key(source_columns)
    tgt_key = canonical_column_key(target_columns)
    with main_db() as conn:
        row = conn.execute(
            """SELECT * FROM attribute_mappings
               WHERE source_connector = ? AND target_connector = ?
                 AND comparison_type = ? AND source_columns_key = ?
                 AND target_columns_key = ?""",
            (source_connector, target_connector, comparison_type, src_key, tgt_key),
        ).fetchone()
    return _row_to_mapping(row) if row else None


def upsert(
    *,
    source_connector: str,
    target_connector: str,
    comparison_type: str,
    source_columns: list[str],
    target_columns: list[str],
    mappings: list[AttributePair],
    provenance: MappingProvenance = MappingProvenance.LIBRARY,
    confidence: float | None = None,
    added_by: str = "system",
    validated_by_run_id: str | None = None,
    details: dict | None = None,
) -> AttributeMapping:
    """Insert or overwrite the canonical row for this key.

    On conflict (same canonical key): overwrite the payload, bump ``version``,
    refresh ``last_used_on`` / ``validated_by_run_id``. ``added_on`` / ``added_by``
    are preserved from the original row.
    """
    src_key = canonical_column_key(source_columns)
    tgt_key = canonical_column_key(target_columns)
    payload = [m.model_dump(mode="json") for m in mappings]
    now = _utcnow()
    details = details or {}

    with main_db() as conn:
        existing = conn.execute(
            """SELECT id, version, added_on, added_by FROM attribute_mappings
               WHERE source_connector = ? AND target_connector = ?
                 AND comparison_type = ? AND source_columns_key = ?
                 AND target_columns_key = ?""",
            (source_connector, target_connector, comparison_type, src_key, tgt_key),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE attribute_mappings
                   SET mappings_json = ?, provenance = ?, confidence = ?,
                       last_used_on = ?, validated_by_run_id = ?, version = ?,
                       details_json = ?
                   WHERE id = ?""",
                (
                    json.dumps(payload), provenance.value, confidence,
                    now.isoformat(), validated_by_run_id, int(existing["version"]) + 1,
                    json.dumps(details), existing["id"],
                ),
            )
            row_id = existing["id"]
        else:
            row_id = new_id()
            conn.execute(
                """INSERT INTO attribute_mappings
                   (id, source_connector, target_connector, comparison_type,
                    source_columns_key, target_columns_key, mappings_json,
                    provenance, confidence, added_by, added_on, last_used_on,
                    validated_by_run_id, version, details_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row_id, source_connector, target_connector, comparison_type,
                    src_key, tgt_key, json.dumps(payload), provenance.value,
                    confidence, added_by, now.isoformat(), now.isoformat(),
                    validated_by_run_id, 1, json.dumps(details),
                ),
            )

    got = get(row_id)
    assert got is not None  # just written
    return got


def touch_last_used(mapping_id: str) -> None:
    """Mark a library row as reused (tier-1 hit)."""
    with main_db() as conn:
        conn.execute(
            "UPDATE attribute_mappings SET last_used_on = ? WHERE id = ?",
            (_utcnow().isoformat(), mapping_id),
        )


def get(mapping_id: str) -> AttributeMapping | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM attribute_mappings WHERE id = ?", (mapping_id,)
        ).fetchone()
    return _row_to_mapping(row) if row else None


def list_mappings(
    *,
    source_connector: str | None = None,
    target_connector: str | None = None,
    comparison_type: str | None = None,
) -> list[AttributeMapping]:
    """Browsable/filterable listing for the Library tab (most-recent first)."""
    clauses: list[str] = []
    params: list[str] = []
    if source_connector:
        clauses.append("source_connector = ?")
        params.append(source_connector)
    if target_connector:
        clauses.append("target_connector = ?")
        params.append(target_connector)
    if comparison_type:
        clauses.append("comparison_type = ?")
        params.append(comparison_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with main_db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM attribute_mappings {where}
                ORDER BY COALESCE(last_used_on, added_on) DESC""",
            params,
        ).fetchall()
    return [_row_to_mapping(r) for r in rows]


def delete(mapping_id: str) -> bool:
    with main_db() as conn:
        cur = conn.execute("DELETE FROM attribute_mappings WHERE id = ?", (mapping_id,))
        return cur.rowcount > 0


def flush() -> int:
    """Empty the whole library (demo cold-start). Returns rows removed."""
    with main_db() as conn:
        cur = conn.execute("DELETE FROM attribute_mappings")
        return cur.rowcount
