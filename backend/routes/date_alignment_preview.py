from __future__ import annotations

import json
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Request

from backend.excel_comparator.core.date_alignment import build_alignment

router = APIRouter()

# Real S/4 and IBP fetches can be thousands of rows serialized as a single
# JSON-string form field — well past FastAPI's default 1MB-per-part limit —
# so the form is parsed manually with a higher cap. See reconcile.py's
# `_MAX_PART_SIZE` for the matching rationale.
_MAX_PART_SIZE = 64 * 1024 * 1024  # 64MB per field


def _load_rows_from_json(rows_json: Optional[str], label: str) -> pd.DataFrame:
    try:
        rows = json.loads(rows_json) if rows_json else []
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: {exc}")

    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail=f"Invalid {label}: expected a list of rows")

    return pd.DataFrame(rows)


@router.post("/api/date-alignment/preview")
async def date_alignment_preview(request: Request) -> dict[str, Any]:
    """Preview the date-range alignment summary for SAP-fetch mode, before reconciliation runs.

    Mirrors the same source_rows/target_rows JSON shape that /reconcile accepts
    in SAP mode, so the frontend can show the same summary right after fetching
    S/4 and IBP data.
    """
    form = await request.form(max_part_size=_MAX_PART_SIZE)

    source_rows = form.get("source_rows")
    target_rows = form.get("target_rows")

    source_df = _load_rows_from_json(str(source_rows) if source_rows is not None else None, "source_rows")
    target_df = _load_rows_from_json(str(target_rows) if target_rows is not None else None, "target_rows")

    return build_alignment(source_df, target_df)
