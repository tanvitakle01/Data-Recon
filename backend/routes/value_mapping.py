"""Run the value-pairing pipeline against currently loaded data.

Thin HTTP wrapper: resolves source/target dataframes from the same
file-or-JSON-rows form shape /automap and /reconcile use, then calls
``recon_engine.value_pairing.pair_values`` for the product (material/PRDID)
and location (plant/LOCID) pairs. Which actual column plays each role is
resolved dynamically — see ``*_product_field``/``*_location_field``/
``*_date_field`` below — so a differently-named Excel header (e.g. "SKU" or
"Plant Code") works exactly like SAP/IBP's canonical "Material"/"PRDID"
names. Callers that don't know the resolved names yet (or old callers) get
those SAP/IBP names as the default, which keeps this endpoint's behavior
unchanged for the live-fetch flow. No pairing logic lives here.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile

from backend.recon_engine.value_pairing import pair_values

# Reuse the manual-form helpers + loaders from the reconcile route so this
# endpoint resolves source/target sides identically to /automap and /reconcile.
from backend.routes.reconcile import (
    _MAX_PART_SIZE,
    _form_optional_str,
    _form_str,
    _form_upload,
    _load_excel_from_upload,
    _load_rows_from_json,
)

router = APIRouter(prefix="/api/recon", tags=["recon-value-mapping"])


def _resolve_df(
    rows_json: Optional[str],
    upload: Optional[UploadFile],
    sheet: str | None,
    label: str,
) -> pd.DataFrame:
    if rows_json is not None:
        return _load_rows_from_json(rows_json, f"{label}_rows")
    if upload is not None:
        return _load_excel_from_upload(upload, sheet)["df"]
    raise HTTPException(
        status_code=400,
        detail=f"Missing {label} data: provide {label}_file or {label}_rows.",
    )


def _col(df: pd.DataFrame, name: str) -> pd.Series | None:
    """Resolve a fixed column name against ``df`` (exact, else case-insensitive)."""
    if name in df.columns:
        return df[name]
    lower = {str(c).lower(): c for c in df.columns}
    match = lower.get(name.lower())
    return df[match] if match is not None else None


@router.post("/value-mapping/run")
async def run_value_mapping(request: Request) -> dict[str, Any]:
    """Pair every distinct product value and every distinct location value.

    Accepts either uploaded Excel files (`source_file`/`target_file`) or
    already-fetched JSON rows (`source_rows`/`target_rows`), matching the
    input modes of /automap and /reconcile. `source_connector`/`target_connector`
    (e.g. "s4", "ibp", "excel") key the value-pair library so approved pairs
    are only reused between the same connector pair. `mapping_sheet` (optional
    JSON) is the parsed mapping-sheet payload, passed through as STM context
    for the LLM pairing step — a hint only, never load-bearing.

    Which column plays the product/location/date role on each side is given
    by `source_product_field`/`target_product_field`/`source_location_field`/
    `target_location_field`/`source_date_field`/`target_date_field` — the
    wizard resolves these from the analyst-confirmed field mapping (so an
    Excel header like "SKU" or "Plant Code" works the same as SAP/IBP's
    canonical "Material"/"ProductionPlant"/"PRDID"/"LOCID"). Any field
    omitted falls back to its SAP/IBP name, which keeps this endpoint's
    behavior unchanged for callers that don't resolve field names themselves.

    Returns ``{"product": ValueMapping, "location": ValueMapping}``.
    """
    form = await request.form(max_part_size=_MAX_PART_SIZE)

    source_file = _form_upload(form, "source_file")
    target_file = _form_upload(form, "target_file")
    source_rows = _form_optional_str(form, "source_rows")
    target_rows = _form_optional_str(form, "target_rows")
    src_sheet = (_form_str(form, "sheet_name_source") or "").strip() or None
    tgt_sheet = (_form_str(form, "sheet_name_target") or "").strip() or None
    source_connector = (_form_str(form, "source_connector") or "").strip() or "excel"
    target_connector = (_form_str(form, "target_connector") or "").strip() or "excel"
    mapping_sheet_raw = _form_optional_str(form, "mapping_sheet")
    mapping_sheet_context: Any = None
    if mapping_sheet_raw:
        try:
            mapping_sheet_context = json.loads(mapping_sheet_raw)
        except ValueError:
            mapping_sheet_context = None

    source_product_field = (_form_str(form, "source_product_field") or "").strip() or "Material"
    target_product_field = (_form_str(form, "target_product_field") or "").strip() or "PRDID"
    source_location_field = (_form_str(form, "source_location_field") or "").strip() or "ProductionPlant"
    target_location_field = (_form_str(form, "target_location_field") or "").strip() or "LOCID"
    source_date_field = (_form_str(form, "source_date_field") or "").strip() or "RequestedDeliveryDate"
    target_date_field = (_form_str(form, "target_date_field") or "").strip() or "PERIODID0_TSTAMP"

    try:
        source_df = _resolve_df(source_rows, source_file, src_sheet, "source")
        target_df = _resolve_df(target_rows, target_file, tgt_sheet, "target")

        source_material = _col(source_df, source_product_field)
        if source_material is None:
            raise HTTPException(status_code=400, detail=f"Source data has no '{source_product_field}' column.")
        target_prdid = _col(target_df, target_product_field)
        if target_prdid is None:
            raise HTTPException(status_code=400, detail=f"Target data has no '{target_product_field}' column.")
        source_plant = _col(source_df, source_location_field)
        if source_plant is None:
            raise HTTPException(status_code=400, detail=f"Source data has no '{source_location_field}' column.")
        target_locid = _col(target_df, target_location_field)
        if target_locid is None:
            raise HTTPException(status_code=400, detail=f"Target data has no '{target_location_field}' column.")

        # Optional date columns for the corroboration check — a record-level
        # signal used only to break a tie when a value has competing
        # candidates (e.g. a coincidental identity match vs. a real
        # transform). Absent columns simply mean corroboration reports "no
        # signal", never a false positive or negative.
        source_dates = _col(source_df, source_date_field)
        target_dates = _col(target_df, target_date_field)

        product = pair_values(
            source_field=source_product_field,
            target_field=target_product_field,
            source_series=source_material,
            target_series=target_prdid,
            source_connector=source_connector,
            target_connector=target_connector,
            mapping_sheet_context=mapping_sheet_context,
            source_dates=source_dates,
            target_dates=target_dates,
        )
        location = pair_values(
            source_field=source_location_field,
            target_field=target_location_field,
            source_series=source_plant,
            target_series=target_locid,
            source_connector=source_connector,
            target_connector=target_connector,
            mapping_sheet_context=mapping_sheet_context,
            source_dates=source_dates,
            target_dates=target_dates,
        )
        return {
            "product": product.model_dump(mode="json"),
            "location": location.model_dump(mode="json"),
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Value pairing failed: {exc}")
