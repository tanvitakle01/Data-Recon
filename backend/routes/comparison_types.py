from __future__ import annotations

from fastapi import APIRouter

from backend.comparison_types.registry import list_comparison_types

router = APIRouter()


@router.get("/api/comparison-types")
async def get_comparison_types():
    return {"comparison_types": list_comparison_types()}
