"""Attribute-mapping Library — read/browse + per-entry delete + demo flush.

Read-oriented surface over :mod:`storage.attribute_mapping_store`. Field
mapping only; nothing here touches value mappings.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.recon_engine.models.audit import AuditAction
from backend.recon_engine.storage import attribute_mapping_store, audit_store

router = APIRouter(prefix="/api/recon/library", tags=["recon-library"])


@router.get("")
def list_library(
    source_connector: Optional[str] = Query(default=None),
    target_connector: Optional[str] = Query(default=None),
    comparison_type: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    """Browse/filter stored mappings (most-recently-used first)."""
    mappings = attribute_mapping_store.list_mappings(
        source_connector=source_connector or None,
        target_connector=target_connector or None,
        comparison_type=comparison_type or None,
    )
    return {"mappings": [m.model_dump(mode="json") for m in mappings]}


@router.delete("/{mapping_id}")
def delete_library_entry(mapping_id: str) -> dict[str, Any]:
    """Delete a single stored mapping."""
    removed = attribute_mapping_store.delete(mapping_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No library mapping '{mapping_id}'.")
    audit_store.record(
        AuditAction.LIBRARY_MAPPING_DELETED,
        entity_type="attribute_mapping",
        entity_id=mapping_id,
    )
    return {"deleted": mapping_id}


@router.post("/flush")
def flush_library(confirm: bool = Query(default=False)) -> dict[str, Any]:
    """DESTRUCTIVE: empty the entire attribute-mapping library (demo reset).

    Requires ``?confirm=true`` as a backend guard on top of the frontend's
    confirmation dialog. Scope is this table only (sibling library stores, when
    they exist, are flushed separately).
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Flush is destructive — call with ?confirm=true to proceed.",
        )
    removed = attribute_mapping_store.flush()
    audit_store.record(
        AuditAction.LIBRARY_FLUSHED,
        entity_type="attribute_mapping",
        entity_id="*",
        details={"removed": removed},
    )
    return {"flushed": removed}
