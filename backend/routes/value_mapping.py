"""Run the value-pairing pipeline against currently loaded data.

Thin HTTP wrapper: resolves source/target dataframes from the same
file-or-JSON-rows form shape /automap and /reconcile use, then calls
``recon_engine.value_pairing.pair_values`` once per confirmed key-field pair
(see ``KeyFieldPair``/``run_key_pairs`` below) — however many the analyst
mapped, not a fixed two. Which actual columns play each pair is given by the
caller's ``key_pairs`` (falls back to ``_DEFAULT_KEY_PAIRS``, the SAP/IBP
canonical Material/PRDID + ProductionPlant/LOCID pair, when omitted — keeping
this endpoint's behavior unchanged for callers that don't resolve field names
themselves). No pairing logic lives here.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from backend.recon_engine.date_detection import is_date_like_series
from backend.recon_engine.models.value_mapping import ValueMapping
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


class KeyFieldPair(BaseModel):
    source_field: str
    target_field: str


# The SAP/IBP canonical pair this endpoint has always defaulted to — kept as
# the fallback so an omitted `key_pairs` reproduces prior behavior for
# callers that don't resolve field names themselves. No date entry here: a
# date pair is only ever recognized from its own VALUES (see
# _split_date_pair), never guessed by name/position, so there's nothing
# deterministic to default it to.
_DEFAULT_KEY_PAIRS: list[KeyFieldPair] = [
    KeyFieldPair(source_field="Material", target_field="PRDID"),
    KeyFieldPair(source_field="ProductionPlant", target_field="LOCID"),
]


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


def _resolve_column(df: pd.DataFrame, name: str, side_label: str) -> pd.Series:
    col = _col(df, name)
    if col is None:
        raise HTTPException(status_code=400, detail=f"{side_label} has no '{name}' column.")
    return col


def _split_date_pair(
    key_pairs: list[KeyFieldPair],
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
) -> tuple[list[KeyFieldPair], KeyFieldPair | None]:
    """Pulls out the one pair whose SOURCE or TARGET column's own sample
    values look like dates (see :func:`recon_engine.date_detection.is_date_like_series`
    — a cheap regex-shape + real parse-attempt check, not a column-name
    guess) as the corroboration-only date pair; every remaining pair is
    pairable. A pair whose column is entirely absent from the data has no
    values to check and is simply not recognized as the date pair — it's
    left pairable like anything else, so a genuinely missing column still
    fails with the usual clear 400 rather than being silently swallowed.
    """
    for index, pair in enumerate(key_pairs):
        source_series = _col(source_df, pair.source_field)
        target_series = _col(target_df, pair.target_field)
        if is_date_like_series(source_series) or is_date_like_series(target_series):
            return key_pairs[:index] + key_pairs[index + 1 :], pair
    return key_pairs, None


def run_key_pairs(
    key_pairs: list[KeyFieldPair],
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    source_label: str,
    pair_fn: Callable[..., ValueMapping],
) -> list[ValueMapping]:
    """Resolves ``source_label``/`"Target data"` columns for every pairable
    key pair (the date pair, if any, is excluded — it's corroboration-only)
    and calls ``pair_fn`` (``pair_values`` or ``pair_values_deterministic_only``)
    once per pair, in input order. Any missing column fails fast with a
    single clear 400, same as before."""
    pairable, date_pair = _split_date_pair(key_pairs or list(_DEFAULT_KEY_PAIRS), source_df, target_df)
    source_dates = _col(source_df, date_pair.source_field) if date_pair else None
    target_dates = _col(target_df, date_pair.target_field) if date_pair else None

    results: list[ValueMapping] = []
    for pair in pairable:
        source_series = _resolve_column(source_df, pair.source_field, source_label)
        target_series = _resolve_column(target_df, pair.target_field, "Target data")
        results.append(
            pair_fn(
                source_field=pair.source_field,
                target_field=pair.target_field,
                source_series=source_series,
                target_series=target_series,
                source_dates=source_dates,
                target_dates=target_dates,
            )
        )
    return results


@router.post("/value-mapping/run")
async def run_value_mapping(request: Request) -> dict[str, Any]:
    """Pair every distinct value for every confirmed key-field pair.

    Accepts either uploaded Excel files (`source_file`/`target_file`) or
    already-fetched JSON rows (`source_rows`/`target_rows`), matching the
    input modes of /automap and /reconcile. `source_connector`/`target_connector`
    (e.g. "s4", "ibp", "excel") key the value-pair library so pairs are only
    reused between the same connector pair. `mapping_sheet` (optional
    JSON) is the parsed mapping-sheet payload, passed through as STM context
    for the LLM pairing step — a hint only, never load-bearing.

    `key_pairs` (optional JSON array of ``{"source_field", "target_field"}``,
    same form-field-holds-JSON convention as `mapping_sheet`) lists every
    confirmed key pair — however many the analyst mapped. Falls back to
    ``_DEFAULT_KEY_PAIRS`` (SAP/IBP's Material/PRDID + ProductionPlant/LOCID)
    when omitted, which keeps this endpoint's behavior unchanged for callers
    that don't resolve field names themselves. Whichever pair's own sample
    VALUES look like dates (a cheap regex-shape + parse-attempt check — see
    ``recon_engine.date_detection``, never a column-name guess) is used for
    corroboration only and never itself paired.

    Returns ``{"pairs": [ValueMapping, ...]}`` in `key_pairs` order (the date
    pair excluded).
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

    key_pairs_raw = _form_optional_str(form, "key_pairs")
    key_pairs: list[KeyFieldPair] = list(_DEFAULT_KEY_PAIRS)
    if key_pairs_raw:
        try:
            key_pairs = [KeyFieldPair(**item) for item in json.loads(key_pairs_raw)]
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid key_pairs: {exc}")

    try:
        source_df = _resolve_df(source_rows, source_file, src_sheet, "source")
        target_df = _resolve_df(target_rows, target_file, tgt_sheet, "target")

        def _pair_fn(**kwargs: Any) -> ValueMapping:
            return pair_values(
                source_connector=source_connector,
                target_connector=target_connector,
                mapping_sheet_context=mapping_sheet_context,
                **kwargs,
            )

        mappings = run_key_pairs(key_pairs, source_df, target_df, "Source data", _pair_fn)
        return {"pairs": [m.model_dump(mode="json") for m in mappings]}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Value pairing failed: {exc}")
