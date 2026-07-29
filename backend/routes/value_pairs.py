"""Value-pair library — browse + per-pair approve/reject + delete + demo flush.

A pair here was already deterministically verified by the value-pairing
pipeline before it was ever written as PENDING (see
``recon_engine.value_pairing``). Approve/reject decides whether it is REUSABLE
by future runs' library-first lookup — it does not retroactively change
whether it applied to the run that proposed it (that already happened, gated
by the HIGH-confidence auto-apply policy in ``engine.executor``).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.recon_engine.models.audit import AuditAction
from backend.recon_engine.models.value_pair import ValuePairStatus
from backend.recon_engine.storage import audit_store, value_pair_store

router = APIRouter(prefix="/api/recon/value-pairs", tags=["recon-value-pairs"])


@router.get("")
def list_value_pairs(
    source_connector: Optional[str] = Query(default=None),
    target_connector: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    """Browse/filter stored value pairs (most-recently-added first)."""
    parsed_status = ValuePairStatus(status) if status else None
    pairs = value_pair_store.list_pairs(
        source_connector=source_connector or None,
        target_connector=target_connector or None,
        status=parsed_status,
    )
    return {"pairs": [p.model_dump(mode="json") for p in pairs]}


@router.post("/{pair_id}/approve")
def approve_value_pair(pair_id: str, actor: str = Query(default="system")) -> dict[str, Any]:
    """Approve a PENDING pair for reuse by future runs' library-first lookup."""
    pair = value_pair_store.approve(pair_id, actor=actor)
    if pair is None:
        raise HTTPException(status_code=404, detail=f"No value pair '{pair_id}'.")
    audit_store.record(
        AuditAction.VALUE_PAIR_APPROVED,
        entity_type="value_pair",
        entity_id=pair_id,
        actor=actor,
    )
    return {"pair": pair.model_dump(mode="json")}


@router.post("/{pair_id}/reject")
def reject_value_pair(
    pair_id: str,
    actor: str = Query(default="system"),
    reason: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    """Reject a PENDING pair — kept as an audit-trail row, never reused."""
    pair = value_pair_store.reject(pair_id, actor=actor, reason=reason)
    if pair is None:
        raise HTTPException(status_code=404, detail=f"No value pair '{pair_id}'.")
    audit_store.record(
        AuditAction.VALUE_PAIR_REJECTED,
        entity_type="value_pair",
        entity_id=pair_id,
        actor=actor,
        details={"reason": reason} if reason else {},
    )
    return {"pair": pair.model_dump(mode="json")}


@router.delete("/{pair_id}")
def delete_value_pair(pair_id: str) -> dict[str, Any]:
    """Delete a single stored value pair."""
    removed = value_pair_store.delete(pair_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No value pair '{pair_id}'.")
    audit_store.record(
        AuditAction.VALUE_PAIR_DELETED,
        entity_type="value_pair",
        entity_id=pair_id,
    )
    return {"deleted": pair_id}


@router.post("/flush")
def flush_value_pairs(confirm: bool = Query(default=False)) -> dict[str, Any]:
    """DESTRUCTIVE: empty the entire value-pair library (demo reset).

    Requires ``?confirm=true`` as a backend guard on top of the frontend's
    confirmation dialog. Scope is this table only — the attribute-mapping
    library is flushed separately via ``POST /api/recon/library/flush``.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Flush is destructive — call with ?confirm=true to proceed.",
        )
    removed = value_pair_store.flush()
    audit_store.record(
        AuditAction.VALUE_PAIR_LIBRARY_FLUSHED,
        entity_type="value_pair",
        entity_id="*",
        details={"removed": removed},
    )
    return {"flushed": removed}
