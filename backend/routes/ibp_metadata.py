from __future__ import annotations

import traceback

from fastapi import APIRouter
from pydantic import BaseModel

from backend.API_conn.connectors.ibp_metadata_service import (
    IBPMetadataService,
)

router = APIRouter(prefix="/api/connectors/ibp")


class IBPFetchRequest(BaseModel):
    entity: str
    properties: list[str]


class IBPPreviewRequest(BaseModel):
    entity: str
    # Optional: when omitted the service previews a safe default selection.
    properties: list[str] | None = None


def _error(exc: Exception) -> dict:
    # Clean message for the UI (SAP/validation errors are already readable);
    # full traceback kept under `detail` for debugging.
    return {
        "success": False,
        "error": str(exc),
        "detail": traceback.format_exc(),
    }


@router.get("/entities")
async def ibp_entities():
    try:
        service = IBPMetadataService()
        return {
            "success": True,
            "entities": service.get_entities(),
        }
    except Exception as exc:
        return _error(exc)


@router.get("/entities/{entity}/properties")
async def ibp_entity_properties(entity: str):
    try:
        service = IBPMetadataService()
        return {
            "success": True,
            "entity": entity,
            "properties": service.get_entity_properties(entity),
            # A mutually-compatible starter selection so the UI can preview
            # immediately (IBP forbids previewing "all" properties).
            "default_properties": service.default_properties(entity),
        }
    except Exception as exc:
        return _error(exc)


# Preview is a POST (not GET) because the selection drives $select and can be
# a long, variable list — IBP planning services reject a select-less read.
@router.post("/preview")
async def ibp_entity_preview(payload: IBPPreviewRequest):
    try:
        service = IBPMetadataService()
        df = service.preview_entity(payload.entity, payload.properties)

        return {
            "success": True,
            "entity": payload.entity,
            "columns": list(df.columns),
            "rows": df.fillna("").to_dict(orient="records"),
        }
    except Exception as exc:
        return _error(exc)


@router.post("/fetch")
async def ibp_fetch(payload: IBPFetchRequest):
    try:
        service = IBPMetadataService()
        df = service.fetch_entity(payload.entity, payload.properties)

        return {
            "success": True,
            "entity": payload.entity,
            "count": len(df),
            "columns": list(df.columns),
            "rows": df.fillna("").to_dict(orient="records"),
        }
    except Exception as exc:
        return _error(exc)
