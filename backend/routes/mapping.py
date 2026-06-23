from __future__ import annotations

from fastapi import APIRouter

from backend.services.mapping_service import auto_map

# Note: repo currently uses difflib-based fuzzy matching in excel_comparator.core.auto_mapper.
# rapidfuzz is not required for functionality because we replicate the Streamlit logic.

router = APIRouter()


@router.post("/auto-map")
async def auto_map_route(payload: dict):
    source_columns = payload.get("source_columns") or []
    target_columns = payload.get("target_columns") or []

    result = auto_map(source_columns=source_columns, target_columns=target_columns)

    # Provide items compatible with Streamlit display: logical/source_col/target_col/role
    # Frontend can use `role` to validate key/compare presence.
    mappings = []
    for item in result.get("display", []):
        src = item.get("source_col")
        tgt = item.get("target_col")
        if not src or not tgt:
            continue

        role = str(item.get("role", ""))
        logical = item.get("logical")

        score = 0.95 if "Key" in role else (0.9 if "Compare" in role else 0.8)
        mappings.append(
            {
                "logical": logical,
                "source": src,
                "target": tgt,
                "role": role,
                "score": float(score),
            }
        )

    return {"mappings": mappings, "mapping": result.get("mapping")}  # mapping is used by /reconcile


