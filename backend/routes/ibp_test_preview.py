from __future__ import annotations

import traceback

from fastapi import APIRouter

from backend.API_conn.connectors.ibp_connector import (
    IBPDemandConnector,
)
from backend.API_conn.odata_utils import sap_odata_date_to_ddmmyyyy

router = APIRouter()


@router.get("/api/ibp/test-preview")
async def ibp_test_preview():

    try:

        connector = IBPDemandConnector()

        df = connector.fetch()

        if "KEYFIGUREDATE" in df.columns:

            df["KEYFIGUREDATE"] = df["KEYFIGUREDATE"].apply(
                sap_odata_date_to_ddmmyyyy
            )

        return {
            "success": True,
            "count": len(df),
            "data": df.fillna("").to_dict(
                orient="records"
            ),
        }

    except Exception as exc:

        return {
            "success": False,
            "error": f"{exc}\n{traceback.format_exc()}",
        }