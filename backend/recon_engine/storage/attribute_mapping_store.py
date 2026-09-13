"""Attribute-mapping library store (in-memory, exact-lookup).

Reuse here is an EXACT-lookup problem — "are these specific source+target
columns present? fetch that validated row" — not a similarity problem, so
this is a plain dict lookup, not a vector index. Dedup is enforced on the
canonical composite key ``(source_connector, target_connector,
comparison_type, source_columns_key, target_columns_key)``.

Conflict policy (confirmed): OVERWRITE + bump ``version`` on store-back — one
canonical row per key, ``last_used_on`` / ``validated_by_run_id`` refreshed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.recon_engine.canonical import canonical_column_key
from backend.recon_engine.models.attribute_mapping import (
    AttributeMapping,
    AttributePair,
    MappingProvenance,
)

_MAPPINGS: dict[str, AttributeMapping] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return "attrmap_" + uuid.uuid4().hex


def _find_key(
    source_connector: str,
    target_connector: str,
    comparison_type: str,
    source_columns_key: str,
    target_columns_key: str,
) -> AttributeMapping | None:
    for mapping in _MAPPINGS.values():
        if (
            mapping.source_connector == source_connector
            and mapping.target_connector == target_connector
            and mapping.comparison_type == comparison_type
            and mapping.source_columns_key == source_columns_key
            and mapping.target_columns_key == target_columns_key
        ):
            return mapping
    return None


def lookup(
    *,
    source_connector: str,
    target_connector: str,
    comparison_type: str,
    source_columns: list[str],
    target_columns: list[str],
) -> AttributeMapping | None:
    """Find a stored mapping for this exact source+target column set.

    Computes the canonical keys with the SAME shared function store-back
    uses, so an identical column set (in any order) resolves to the same
    row. Pure read — the caller calls :func:`touch_last_used` on a genuine
    hit.
    """
    src_key = canonical_column_key(source_columns)
    tgt_key = canonical_column_key(target_columns)
    return _find_key(source_connector, target_connector, comparison_type, src_key, tgt_key)


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
    refresh ``last_used_on`` / ``validated_by_run_id``. ``added_on`` /
    ``added_by`` are preserved from the original row.
    """
    src_key = canonical_column_key(source_columns)
    tgt_key = canonical_column_key(target_columns)
    now = _utcnow()
    details = details or {}

    existing = _find_key(source_connector, target_connector, comparison_type, src_key, tgt_key)
    row_id = existing.id if existing else new_id()
    added_on = existing.added_on if existing else now
    added_by_final = existing.added_by if existing else added_by
    version = (existing.version + 1) if existing else 1

    mapping = AttributeMapping(
        id=row_id,
        source_connector=source_connector,
        target_connector=target_connector,
        comparison_type=comparison_type,
        source_columns_key=src_key,
        target_columns_key=tgt_key,
        mappings=mappings,
        provenance=provenance,
        confidence=confidence,
        added_by=added_by_final,
        added_on=added_on,
        last_used_on=now,
        validated_by_run_id=validated_by_run_id,
        version=version,
        details=details,
    )
    _MAPPINGS[row_id] = mapping
    return mapping


def touch_last_used(mapping_id: str) -> None:
    """Mark a library row as reused (tier-1 hit)."""
    mapping = _MAPPINGS.get(mapping_id)
    if mapping is not None:
        _MAPPINGS[mapping_id] = mapping.model_copy(update={"last_used_on": _utcnow()})


def get(mapping_id: str) -> AttributeMapping | None:
    return _MAPPINGS.get(mapping_id)


def list_mappings(
    *,
    source_connector: str | None = None,
    target_connector: str | None = None,
    comparison_type: str | None = None,
) -> list[AttributeMapping]:
    """Browsable/filterable listing (most-recent first)."""
    values = list(_MAPPINGS.values())
    if source_connector:
        values = [m for m in values if m.source_connector == source_connector]
    if target_connector:
        values = [m for m in values if m.target_connector == target_connector]
    if comparison_type:
        values = [m for m in values if m.comparison_type == comparison_type]
    return sorted(values, key=lambda m: m.last_used_on or m.added_on, reverse=True)


def delete(mapping_id: str) -> bool:
    if mapping_id in _MAPPINGS:
        del _MAPPINGS[mapping_id]
        return True
    return False


def flush() -> int:
    """Empty the whole library (demo cold-start). Returns rows removed."""
    count = len(_MAPPINGS)
    _MAPPINGS.clear()
    return count
