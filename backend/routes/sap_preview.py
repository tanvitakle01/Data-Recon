from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException

from backend.API_conn.services.reconcilation_service import ReconciliationService

router = APIRouter()


def _df_to_payload(df: pd.DataFrame) -> dict[str, Any]:
    if df is None:
        df = pd.DataFrame()

    # Ensure consistent JSON types
    cols = list(df.columns)
    head = df.head(5)
    preview_records = head.astype(str).to_dict(orient="records")

    return {
        "rows": int(len(df)),
        "cols": int(len(cols)),
        "columns": cols,
        "preview": preview_records,
    }


@router.post("/sap-preview")
async def sap_preview():
    try:
        service = ReconciliationService()

        source_df = service.get_source_data()
        target_df = service.get_target_data()

        return {
            "source": _df_to_payload(source_df),
            "target": _df_to_payload(target_df),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"SAP preview failed: {exc}")

