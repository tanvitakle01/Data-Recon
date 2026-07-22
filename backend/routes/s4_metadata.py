from __future__ import annotations

import traceback

from fastapi import APIRouter
from pydantic import BaseModel

from backend.API_conn.connectors.s4_metadata_service import (
    S4MetadataService,
)
from backend.recon_engine.matching import evaluate_side

router = APIRouter(prefix="/api/connectors/s4")


class S4KeyPair(BaseModel):
    left: str
    right: str


class S4Join(BaseModel):
    entity: str
    properties: list[str] = []
    type: str = "left"  # "left" | "inner"
    keys: list[S4KeyPair] = []


class S4Primary(BaseModel):
    entity: str
    properties: list[str] = []


class S4JoinSpec(BaseModel):
    primary: S4Primary
    joins: list[S4Join] = []


def _error(exc: Exception) -> dict:
    return {"success": False, "error": str(exc), "detail": traceback.format_exc()}


def _spec_dict(payload: S4JoinSpec) -> dict:
    return {
        "primary": payload.primary.model_dump(),
        "joins": [
            {
                "entity": j.entity,
                "properties": j.properties,
                "type": j.type,
                "keys": [{"left": k.left, "right": k.right} for k in j.keys],
            }
            for j in payload.joins
        ],
    }


@router.get("/entities")
async def s4_entities():
    try:
        return {"success": True, "entities": S4MetadataService().get_entities()}
    except Exception as exc:
        return _error(exc)


@router.get("/entities/{entity}/properties")
async def s4_entity_properties(entity: str):
    try:
        service = S4MetadataService()
        return {
            "success": True,
            "entity": entity,
            "properties": service.get_entity_properties(entity),
            "keys": service.get_entity_keys(entity),
        }
    except Exception as exc:
        return _error(exc)


@router.get("/entities/{entity}/relationships")
async def s4_entity_relationships(entity: str):
    try:
        service = S4MetadataService()
        return {
            "success": True,
            "entity": entity,
            "relationships": service.get_entity_relationships(entity),
        }
    except Exception as exc:
        return _error(exc)


# Preview + fetch take a join spec; POST because the spec is a structured,
# variable-size body (primary + joins + composite keys).
@router.post("/preview")
async def s4_preview(payload: S4JoinSpec):
    try:
        service = S4MetadataService()
        df = service.preview_join(_spec_dict(payload))
        return {
            "success": True,
            "columns": list(df.columns),
            "rows": df.fillna("").to_dict(orient="records"),
        }
    except Exception as exc:
        return _error(exc)


@router.post("/fetch")
async def s4_fetch(payload: S4JoinSpec):
    try:
        service = S4MetadataService()
        df = service.fetch_joined_dataset(_spec_dict(payload))
        return {
            "success": True,
            "count": len(df),
            "columns": list(df.columns),
            "rows": df.fillna("").to_dict(orient="records"),
            # MDT auxiliary evidence recommendation for the SOURCE side, so the
            # "Recommended for Deterministic Mapping" panel can render on the
            # data preview. Evidence-only; never mapping/reconciliation data.
            "auxiliary_fields": evaluate_side(df, "source"),
        }
    except Exception as exc:
        return _error(exc)
