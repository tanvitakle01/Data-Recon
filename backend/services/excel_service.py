from __future__ import annotations

from io import BytesIO
from typing import Any, Optional

import pandas as pd

from backend.excel_comparator.core.loader import load_excel  # type: ignore


def excel_upload_to_frame(file_bytes: bytes, sheet_name: str | None = None) -> dict[str, Any]:
    """Load an uploaded excel file into a structured dict.

    Returns keys compatible with backend/excel_comparator/core/loader.py
    plus the raw bytes for writer.
    """
    payload = load_excel(BytesIO(file_bytes), sheet_name=sheet_name)
    payload["bytes"] = file_bytes
    return payload


def records_to_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records)


def frame_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    # keep as native python types where possible
    return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")

