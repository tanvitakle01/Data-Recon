"""Run the deterministic value-mapping engine against currently loaded data.

Thin HTTP wrapper: resolves source/target dataframes from the same
file-or-JSON-rows form shape /automap and /reconcile use, then calls the
existing, tested matchers in ``recon_engine.matching`` unchanged. No matching
logic lives here.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile

from backend.recon_engine.matching import (
    SOURCE_PLANT_SEEDS,
    SOURCE_PRODUCT_SEEDS,
    TARGET_LOCATION_SEEDS,
    TARGET_PRODUCT_SEEDS,
    confirmed_series,
    first_confirmed_series,
    match_locations,
    match_products,
    recommend_auxiliary_fields,
)
from backend.recon_engine.matching.auxiliary import (
    ROLE_LOCATION_ALT_NAME,
    ROLE_PRODUCT_ALT_ID,
    ROLE_PRODUCT_DESCRIPTION,
    ROLE_PRODUCT_GROUP,
    ROLE_SOURCE_MATERIAL_GROUP,
    ROLE_SOURCE_PRODUCT_DESCRIPTION,
)

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
    """Resolve a fixed column name against ``df`` (exact, else case-insensitive).

    Returns ``None`` when the column isn't present — the matchers already
    treat an absent optional column as "unreachable" (see their docstrings),
    so this never fabricates data.
    """
    if name in df.columns:
        return df[name]
    lower = {str(c).lower(): c for c in df.columns}
    match = lower.get(name.lower())
    return df[match] if match is not None else None


@router.post("/value-mapping/run")
async def run_value_mapping(request: Request) -> dict[str, Any]:
    """Match every distinct Material -> PRDID and ProductionPlant -> LOCID value.

    Accepts either uploaded Excel files (`source_file`/`target_file`) or
    already-fetched JSON rows (`source_rows`/`target_rows`), matching the
    input modes of /automap and /reconcile.

    Returns ``{"product": ValueMapping, "location": ValueMapping}``.
    """
    form = await request.form(max_part_size=_MAX_PART_SIZE)

    source_file = _form_upload(form, "source_file")
    target_file = _form_upload(form, "target_file")
    source_rows = _form_optional_str(form, "source_rows")
    target_rows = _form_optional_str(form, "target_rows")
    src_sheet = (_form_str(form, "sheet_name_source") or "").strip() or None
    tgt_sheet = (_form_str(form, "sheet_name_target") or "").strip() or None

    try:
        source_df = _resolve_df(source_rows, source_file, src_sheet, "source")
        target_df = _resolve_df(target_rows, target_file, tgt_sheet, "target")

        source_material = _col(source_df, "Material")
        if source_material is None:
            raise HTTPException(status_code=400, detail="Source data has no 'Material' column.")
        target_prdid = _col(target_df, "PRDID")
        if target_prdid is None:
            raise HTTPException(status_code=400, detail="Target data has no 'PRDID' column.")
        source_plant = _col(source_df, "ProductionPlant")
        if source_plant is None:
            raise HTTPException(status_code=400, detail="Source data has no 'ProductionPlant' column.")
        target_locid = _col(target_df, "LOCID")
        if target_locid is None:
            raise HTTPException(status_code=400, detail="Target data has no 'LOCID' column.")

        # MDT Auxiliary Field Recommender: existence + population checks against
        # the live fetched data, tier-ranked. The confirmed candidates are fed
        # to the matchers as evidence — they never enter business_key/
        # compare_fields/shadow/reconcile output (kept strictly as matcher args).
        target_product_aux = recommend_auxiliary_fields(target_df, TARGET_PRODUCT_SEEDS)
        target_location_aux = recommend_auxiliary_fields(target_df, TARGET_LOCATION_SEEDS)
        source_product_aux = recommend_auxiliary_fields(source_df, SOURCE_PRODUCT_SEEDS)
        source_plant_aux = recommend_auxiliary_fields(source_df, SOURCE_PLANT_SEEDS)

        product = match_products(
            source_material=source_material,
            source_material_group=first_confirmed_series(
                source_df, source_product_aux, ROLE_SOURCE_MATERIAL_GROUP
            ),
            target_prdid=target_prdid,
            target_prodgroup=first_confirmed_series(
                target_df, target_product_aux, ROLE_PRODUCT_GROUP
            ),
            target_descriptions=confirmed_series(
                target_df, target_product_aux, ROLE_PRODUCT_DESCRIPTION
            ),
            target_alt_ids=confirmed_series(target_df, target_product_aux, ROLE_PRODUCT_ALT_ID),
            source_order_item_text=first_confirmed_series(
                source_df, source_product_aux, ROLE_SOURCE_PRODUCT_DESCRIPTION
            ),
        )
        location = match_locations(
            source_plant=source_plant,
            target_locid=target_locid,
            target_alt_names=confirmed_series(
                target_df, target_location_aux, ROLE_LOCATION_ALT_NAME
            ),
        )
        return {
            "product": product.model_dump(mode="json"),
            "location": location.model_dump(mode="json"),
            # Recommended-for-Deterministic-Mapping evidence fields, surfaced to
            # the human on the Mapping Review page (tier + fill rate + whether a
            # current rule consumes it). Evidence-only; never reconciliation data.
            "auxiliary_fields": {
                "target_product": [c.model_dump(mode="json") for c in target_product_aux],
                "target_location": [c.model_dump(mode="json") for c in target_location_aux],
                "source_product": [c.model_dump(mode="json") for c in source_product_aux],
                "source_plant": [c.model_dump(mode="json") for c in source_plant_aux],
            },
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Deterministic mapping failed: {exc}")
