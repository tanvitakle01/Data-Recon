from __future__ import annotations

import json
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile

from backend.recon_engine import attribute_library
from backend.recon_engine.field_mapper import infer_field_mapping
from backend.recon_engine.llm import reset_llm_outcome

# Reuse the manual-form helpers + loaders from the reconcile route so this
# endpoint resolves source/target sides identically to /automap (files or JSON
# rows). The wizard already strips MDT auxiliary fields from the rows before
# sending, so they never reach the field-mapping inference.
from backend.routes.reconcile import (
    _MAX_PART_SIZE,
    _form_optional_str,
    _form_str,
    _form_upload,
    _load_excel_from_upload,
    _load_rows_from_json,
)

router = APIRouter(prefix="/api/recon", tags=["recon-mapping-infer"])


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


def _parse_columns(raw: Optional[str]) -> list[str]:
    """Parse a JSON array of column names (the full per-side dataset columns).

    Best-effort: a malformed/absent value yields an empty list, which simply
    disables the library lookup (fall through to the LLM) rather than erroring.
    """
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [str(c) for c in value] if isinstance(value, list) else []


def _is_truthy(raw: Optional[str]) -> bool:
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


@router.post("/mapping/infer")
async def infer_mapping_route(request: Request) -> dict[str, Any]:
    """Three-tier source→target FIELD mapping for the no-mapping-sheet path.

    Tier 1 — the attribute-mapping LIBRARY. When the connectors, comparison
    type, and full per-side column lists are supplied (and `regenerate` is not
    set), the canonical column-set key is looked up; a hit returns a mapping
    labeled "Generated via Vector Library" without any LLM call.

    Tier 2 — the LLM. On a library miss (or `regenerate=true`), infer via the
    Groq→OpenAI failover client; each row is tagged with the provider that
    answered so the card shows "Generated via Groq/OpenAI".

    Accepts the same multipart form as /automap — uploaded Excel files
    (`source_file`/`target_file`) or already-fetched JSON rows
    (`source_rows`/`target_rows`) — and returns the same `{display, mapping}`
    shape the Step-4 table consumes, plus the LLM provider-failover surface.

    Column-to-column (FIELD) mapping only — it never emits value-level pairs
    (that stays the deterministic matcher's job). Degrades to an empty mapping
    (never raises) when no AI provider is configured or the call fails, so the
    user can build the field mapping manually.
    """
    form = await request.form(max_part_size=_MAX_PART_SIZE)

    source_file = _form_upload(form, "source_file")
    target_file = _form_upload(form, "target_file")
    source_rows = _form_optional_str(form, "source_rows")
    target_rows = _form_optional_str(form, "target_rows")
    src_sheet = (_form_str(form, "sheet_name_source") or "").strip() or None
    tgt_sheet = (_form_str(form, "sheet_name_target") or "").strip() or None

    # Library-lookup key parts (optional — the LLM path works without them).
    source_connector = (_form_str(form, "source_connector") or "").strip()
    target_connector = (_form_str(form, "target_connector") or "").strip()
    comparison_type = (_form_str(form, "comparison_type") or "").strip()
    source_columns = _parse_columns(_form_optional_str(form, "source_columns"))
    target_columns = _parse_columns(_form_optional_str(form, "target_columns"))
    regenerate = _is_truthy(_form_str(form, "regenerate"))

    # ── Tier 1: library first ────────────────────────────────────────────────
    if not regenerate and source_connector and target_connector and comparison_type \
            and source_columns and target_columns:
        hit = attribute_library.library_result_for(
            source_connector=source_connector,
            target_connector=target_connector,
            comparison_type=comparison_type,
            source_columns=source_columns,
            target_columns=target_columns,
        )
        if hit is not None:
            return hit

    # ── Tier 2: LLM (Groq → OpenAI) ──────────────────────────────────────────
    try:
        source_df = _resolve_df(source_rows, source_file, src_sheet, "source")
        target_df = _resolve_df(target_rows, target_file, tgt_sheet, "target")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    reset_llm_outcome()  # clear any prior provider outcome for this request
    result = infer_field_mapping(source_df, target_df)

    # Stamp each row with the provider that actually answered (groq/openai) so
    # the card labels the source precisely; leave "generated" when degraded.
    provider = result.get("provider")
    if provider in ("groq", "openai"):
        for row in result.get("display", []):
            row["provenance"] = provider
    result["source"] = "llm"
    return result
