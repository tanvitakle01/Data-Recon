from __future__ import annotations

import traceback
from typing import Any

from fastapi import APIRouter

from backend.API_conn.connectors.s4_connector import (
    S4SalesOrderConnector,
)

router = APIRouter()


def _sap_odata_date_to_ddmmyyyy(value):

    if not value:
        return ""

    s = str(value)

    if s.startswith("/Date("):

        digits = "".join(
            ch for ch in s if ch.isdigit()
        )

        if digits:

            import datetime

            dt = datetime.datetime.utcfromtimestamp(
                int(digits) / 1000
            )

            return dt.strftime("%d.%m.%Y")

    return s


@router.get("/api/s4/test-preview")
async def s4_test_preview():

    try:

        connector = S4SalesOrderConnector()

        df = connector.fetch()

        if "ReqDlvDate" in df.columns:

            df["ReqDlvDate"] = df["ReqDlvDate"].apply(
                _sap_odata_date_to_ddmmyyyy
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