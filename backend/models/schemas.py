from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PreviewResponse(BaseModel):
    filename: str
    rows: int
    cols: int
    columns: list[str]
    # first 5 rows as records: [{col1: v1, col2: v2, ...}, ...]
    preview: list[dict[str, Any]]


class AutoMapRequest(BaseModel):
    source_columns: list[str] = Field(..., min_items=1)
    target_columns: list[str] = Field(..., min_items=1)


class AutoMapItem(BaseModel):
    source: str
    target: str
    score: float


class AutoMapResponse(BaseModel):
    mappings: list[AutoMapItem]
    # extra info used by UI (optional but helpful)
    # mappings_to_display: list[{logical, source_col, target_col, role}]


class ReconcileRequest(BaseModel):
    source_data: list[dict[str, Any]]
    target_data: list[dict[str, Any]]
    mapping: dict[str, Any]

    # filenames/sheet names are optional; only needed to build output excel widths
    original_target_filename: Optional[str] = None
    original_target_sheet_name: Optional[str] = None


class ReconcileSummary(BaseModel):
    total_records: int
    matched: int
    unmatched: int
    match_percentage: float

    qty_mismatch: Optional[int] = None
    missing_in_target: Optional[int] = None
    extra_in_target: Optional[int] = None


class ReconcileResponse(BaseModel):
    summary: ReconcileSummary
    matched_records: list[dict[str, Any]]
    unmatched_records: list[dict[str, Any]]
    # annotated Excel is returned via separate download endpoint (recommended)
    # to keep the JSON small.

