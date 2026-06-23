from __future__ import annotations

import traceback
from typing import Any

from fastapi import APIRouter

from backend.API_conn.connectors.s4_connector import S4SalesOrderConnector

router = APIRouter()


def _sap_odata_date_to_ddmmyyyy(value: Any) -> str:
    """Convert SAP OData V2 /Date(1522800000000)/ to DD.MM.YYYY."""

    if value is None:
        return ""

    s = str(value).strip()
    if not s:
        return ""

    # Handles: /Date(1522800000000)/
    m = None
    if s.startswith("/Date(") and s.endswith(")/"):
        inner = s[len("/Date(") : -len(")/")]
        # sometimes SAP includes ms offset /Date(....+0000)/
        # take leading number token
        token = inner.split("+")[0].split("-")[0] if ("+" in inner or "-" in inner) else inner
        token = token.strip()
        if token.isdigit():
            m = int(token)

    # fallback: try to parse digits from any /Date(...)/ payload
    if m is None and s.startswith("/Date("):
        digits = "".join(ch for ch in s if ch.isdigit())
        if digits:
            m = int(digits)

    if m is None:
        # already a formatted string? return as-is
        return s

    try:
        import datetime as _dt

        dt = _dt.datetime.utcfromtimestamp(m / 1000.0)
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return s


def _first_present(row: dict[str, Any], keys: list[str]) -> Any:
    for k in keys:
        if k in row and row.get(k) not in (None, ""):
            return row.get(k)
    return ""


@router.get("/api/s4/test-preview")
async def s4_test_preview() -> dict[str, Any]:
    try:
        print("S4 TEST PREVIEW CALLED")

        connector = S4SalesOrderConnector()

        # The current connector previously queried header-level A_SalesOrder.
        # In this system we must verify where Material/Plant/ReqDlv* actually live.
        # Try schedule-line / item first; fallback to header.
        # NOTE: If header-level is the only one available, Material/Plant will be empty,
        # but the frontend mapping will still work.
        candidate_entity_sets = [
            "A_SalesOrderScheduleLine",
            "SalesOrderScheduleLine",
            "A_SalesOrderItem",
            "SalesOrderItem",
            "A_SalesOrderScheduleLineTP",
            "SalesOrderScheduleLineTP",
            "A_SalesOrder",  # fallback (may not include Material/Plant)
        ]


        raw_records: list[dict[str, Any]] = []
        for es in candidate_entity_sets:
            records = connector.fetch_entity_set(entity_set=es, top=10)
            if records:
                raw_records = records
                break

        mapped: list[dict[str, Any]] = []

        # Diagnostic: show what keys the chosen entity set actually returns.
        if raw_records:
            try:
                print("FIRST RAW RECORD KEYS:", list(raw_records[0].keys()))
                print("FIRST RAW RECORD:", raw_records[0])
            except Exception:
                pass

        for r in raw_records:

            sales_order = _first_present(
                r,
                [
                    "SalesOrder",
                    "VBELN",
                    "SalesOrderNum",
                    "Vbeln",
                    "A_SalesOrder",
                ],
            )

            sales_order_type = _first_present(
                r,
                [
                    "SalesOrderType",
                    "Auart",
                    "OrderType",
                    "VBTYP",
                ],
            )

            # NOTE: In some schedule-line / item entity sets, the plant field is not named SoldToParty.
            # Keep a broader candidate list for plant-like fields.
            sold_to = _first_present(
                r,
                [
                    # Common plant representations
                    "Plnt",
                    "Plant",
                    "WERKS",
                    "PlantNumber",
                    "PlantId",
                    "respectivePlnt",
                    # Fallbacks (some systems might store it differently)
                    "SoldToParty",
                    "KUNNR",
                    "Customer",
                    "ShipToParty",
                ],
            )


            req_dlv_dt_raw = _first_present(
                r,
                [
                    "RequestedDeliveryDate",
                    "ReqDlvDt",
                    "EDDAT",
                    "Req.dlv.dt",
                ],
            )

            # ReqDlvQty should come from quantity/schedule/order qty fields (not net value).
            total_net_amount_raw = _first_present(
                r,
                [
                    # Common qty representations
                    "ReqDlvQty",
                    "RequestedQuantity",
                    "OrderQuantity",
                    "TargetQuantity",
                    "RequestedQty",
                    "OrderQty",
                    "ReqQty",
                    "MENGE",
                    "Quantity",
                    "RequestedQuantities",
                    # Sometimes quantities are returned on schedule line with generic names
                    "QuantityInSalesUnit",
                    "TargetQty",
                    # Fallbacks (old approach - may be absent in current entity set)
                    "TotalNetAmount",
                    "NetAmount",
                    "TotalNetValue",
                    "NETWR",
                    "NetAmountAmount",
                    "TotalNetAmountInOverall",
                ],
            )


            # Normalize amount to string with 2 decimals when possible.
            total_net_amount: Any = total_net_amount_raw
            try:
                if isinstance(total_net_amount_raw, str) and total_net_amount_raw.strip() == "":
                    total_net_amount = ""
                else:
                    total_net_amount = f"{float(total_net_amount_raw):.2f}"
            except Exception:
                # keep original (string/number) if formatting fails
                total_net_amount = total_net_amount_raw

            # TEMP: reconciliation MVP mapping into IBP-style structure.
            # Until we fetch item-level entities that actually contain Material/Plant/Order Qty,
            # we map header-level fields into the expected IBP-like keys.
            mapped.append(
                {
                    "Material": sales_order,
                    "Plnt": sold_to,
                    "ReqDlvDt": _sap_odata_date_to_ddmmyyyy(req_dlv_dt_raw),
                    "ReqDlvQty": str(total_net_amount) if total_net_amount is not None else "",
                }
            )


        # This endpoint is used for preview; callers expect the count to match returned rows.
        return {
            "success": True,
            "count": int(len(mapped)),
            "data": mapped,
        }

    except Exception as exc:
        error_text = f"{exc}\n{traceback.format_exc()}"
        return {
            "success": False,
            "error": error_text,
        }

