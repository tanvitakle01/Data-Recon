"""Value-pair library store (in-memory, exact-lookup).

Mirrors ``attribute_mapping_store.py``'s conventions: dedup enforced on the
canonical composite key ``(source_connector, target_connector, source_field,
target_field, source_value, target_value)``.

Conflict policy differs deliberately from the attribute-mapping library:
:func:`propose` never overwrites an existing row. Once a pair has been
proposed, a later pipeline run proposing the same source value returns the
existing row unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from backend.recon_engine.models.value_pair import ValuePair

_PAIRS: dict[str, ValuePair] = {}
_STATUS: dict[str, str] = {}  # pair_id -> 'promoted' | 'provisional'
_RUN_SCOPE: dict[str, str | None] = {}  # pair_id -> graph_run_id


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return "valpair_" + uuid.uuid4().hex


def get(pair_id: str) -> ValuePair | None:
    return _PAIRS.get(pair_id)


def _find_exact(
    source_connector: str,
    target_connector: str,
    source_field: str,
    target_field: str,
    source_value: str,
    target_value: str,
) -> ValuePair | None:
    for pair in _PAIRS.values():
        if (
            pair.source_connector == source_connector
            and pair.target_connector == target_connector
            and pair.source_field == source_field
            and pair.target_field == target_field
            and pair.source_value == source_value
            and pair.target_value == target_value
        ):
            return pair
    return None


def lookup_pairs(
    *,
    source_connector: str,
    target_connector: str,
    source_field: str,
    target_field: str,
    graph_run_id: str | None = None,
) -> dict[str, ValuePair]:
    """Every stored pair for this field pair, keyed by ``source_value``,
    visible to ``graph_run_id`` — every globally 'promoted' row, plus any
    'provisional' row THIS run itself discovered earlier. A caller with no
    run identity (``graph_run_id=None`` — Manual mode, live-pairing) only ever
    sees promoted rows.
    """
    out: dict[str, ValuePair] = {}
    for pair_id, pair in _PAIRS.items():
        if not (
            pair.source_connector == source_connector
            and pair.target_connector == target_connector
            and pair.source_field == source_field
            and pair.target_field == target_field
        ):
            continue
        status = _STATUS.get(pair_id, "promoted")
        if status == "promoted" or (status == "provisional" and _RUN_SCOPE.get(pair_id) == graph_run_id):
            out[pair.source_value] = pair
    return out


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
    graph_run_id: str | None = None,
) -> ValuePair:
    """Persist a freshly-verified pairing (an ordered ops chain).

    If a row already exists for this exact key, it is returned unchanged —
    see the module docstring on conflict policy. ``target_value`` is part of
    the lookup key so a genuinely different target proposed for the same
    source value inserts its OWN row instead of being handed back an
    unrelated target's row (one-to-many support).

    ``graph_run_id``, when given, tags a freshly-inserted row 'provisional'
    (visible only to that run — see :func:`lookup_pairs` — until
    :func:`promote_run` marks it 'promoted' at that run's successful finalize,
    or :func:`discard_run` deletes it if the run never gets there). Omitted
    (``None``) for Manual mode/live-pairing, which have no run identity —
    those rows are 'promoted' immediately.
    """
    evidence = evidence or {}
    existing = _find_exact(
        source_connector, target_connector, source_field, target_field, source_value, target_value
    )
    if existing:
        if _STATUS.get(existing.id) == "provisional" and _RUN_SCOPE.get(existing.id) != graph_run_id:
            _STATUS[existing.id] = "promoted"
        return existing

    pair_id = new_id()
    pair = ValuePair(
        id=pair_id,
        source_connector=source_connector,
        target_connector=target_connector,
        source_field=source_field,
        target_field=target_field,
        source_value=source_value,
        target_value=target_value,
        ops=ops,
        evidence=evidence,
        added_by=added_by,
        added_on=_utcnow(),
        version=1,
    )
    _PAIRS[pair_id] = pair
    _STATUS[pair_id] = "provisional" if graph_run_id else "promoted"
    _RUN_SCOPE[pair_id] = graph_run_id
    return pair


def promote_run(graph_run_id: str) -> int:
    """Marks every 'provisional' row this run discovered as 'promoted' —
    called once, at that run's successful finalize. Returns the number of
    rows promoted."""
    count = 0
    for pair_id in list(_PAIRS):
        if _STATUS.get(pair_id) == "provisional" and _RUN_SCOPE.get(pair_id) == graph_run_id:
            _STATUS[pair_id] = "promoted"
            count += 1
    return count


def discard_run(graph_run_id: str) -> int:
    """Deletes every 'provisional' row this run discovered — called whenever a
    run's lifecycle ends without completing, so a discarded run's
    still-unverified guesses never leak into another run's library lookups.
    Returns the number of rows removed."""
    count = 0
    for pair_id in list(_PAIRS):
        if _STATUS.get(pair_id) == "provisional" and _RUN_SCOPE.get(pair_id) == graph_run_id:
            del _PAIRS[pair_id]
            _STATUS.pop(pair_id, None)
            _RUN_SCOPE.pop(pair_id, None)
            count += 1
    return count


def delete(pair_id: str) -> bool:
    if pair_id in _PAIRS:
        del _PAIRS[pair_id]
        _STATUS.pop(pair_id, None)
        _RUN_SCOPE.pop(pair_id, None)
        return True
    return False


def flush() -> int:
    """Empty the whole value-pair library (demo cold-start). Returns rows removed."""
    count = len(_PAIRS)
    _PAIRS.clear()
    _STATUS.clear()
    _RUN_SCOPE.clear()
    return count


def list_pairs(
    *,
    source_connector: str | None = None,
    target_connector: str | None = None,
) -> list[ValuePair]:
    """Browsable/filterable listing (most-recent first)."""
    values = list(_PAIRS.values())
    if source_connector:
        values = [p for p in values if p.source_connector == source_connector]
    if target_connector:
        values = [p for p in values if p.target_connector == target_connector]
    return sorted(values, key=lambda p: p.added_on, reverse=True)
