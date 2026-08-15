"""Live, LLM-free value-pairing pre-pass — reflects the CURRENT recipe.

The merged Mapping card's Mapping Review must update live as the user edits a
recipe step touching a Key field, without ever triggering an LLM call — only
an explicit "Run AI-mapping" click does that (``POST
/api/recon/value-mapping/run``, ``value_mapping.py``). This endpoint runs the
CURRENT recipe's filter/transform steps (never aggregation — that changes row
grain and should not run before pairing) against the FULL current source
dataset via the same deterministic executor a real run uses, then resolves
values via ``pair_values_deterministic_only`` (library lookup + identity match
only — see ``recon_engine.value_pairing.pipeline``), once per confirmed key
pair (see ``value_mapping.run_key_pairs``) — however many, not a fixed two.

Returns the same ``{"pairs": [ValueMapping, ...]}`` shape ``/value-mapping/run``
does, so the frontend's merge logic is agnostic to which endpoint produced a
given match.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.recon_engine.engine.executor import build_shadow_source
from backend.recon_engine.models.contract import DraftContract
from backend.recon_engine.operations import get_operation
from backend.recon_engine.operations.registry import OperationKind
from backend.recon_engine.value_pairing import pair_values_deterministic_only
from backend.routes.value_mapping import KeyFieldPair, _DEFAULT_KEY_PAIRS, run_key_pairs

router = APIRouter(prefix="/api/recon", tags=["recon-value-mapping"])


class LivePairingPrepassRequest(BaseModel):
    source_rows: list[dict[str, Any]] = Field(default_factory=list)
    target_rows: list[dict[str, Any]] = Field(default_factory=list)
    # Current recipe steps (raw ContractOperation dicts) — AGGREGATE-kind ops
    # are dropped below; only filters/transforms run ahead of pairing.
    operations: list[dict[str, Any]] = Field(default_factory=list)
    source_schema: list[str] = Field(default_factory=list)
    target_schema: list[str] = Field(default_factory=list)
    comparison_type: str = "custom"
    source_connector: str = "excel"
    target_connector: str = "excel"
    key_pairs: list[KeyFieldPair] = Field(default_factory=lambda: list(_DEFAULT_KEY_PAIRS))


def _live_recipe_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter/transform ops only, in authored order — skips AGGREGATE ops (row
    grain shouldn't change before pairing) and any op name that isn't
    allow-listed (defensive: a mid-edit recipe step may reference an op that
    hasn't been fully configured yet; this must never 500)."""
    live: list[dict[str, Any]] = []
    for op in operations:
        try:
            spec = get_operation(op.get("op", ""))
        except KeyError:
            continue
        if spec.kind in (OperationKind.FILTER, OperationKind.TRANSFORM):
            live.append(op)
    return live


@router.post("/value-mapping/live-prepass")
def live_pairing_prepass(req: LivePairingPrepassRequest) -> dict[str, Any]:
    """Recipe-aware, LLM-free pre-pass: run the current recipe's filters and
    transforms over the FULL source dataset (no sampling — matches how a real
    run's executor sees the data), then resolve every confirmed key pair's
    values via library lookup + identity match only."""
    if not req.source_rows:
        raise HTTPException(status_code=400, detail="Missing source data: provide source_rows.")
    if not req.target_rows:
        raise HTTPException(status_code=400, detail="Missing target data: provide target_rows.")

    source_df = pd.DataFrame(req.source_rows)
    target_df = pd.DataFrame(req.target_rows)

    draft = DraftContract(
        comparison_type=req.comparison_type,
        source_type=req.source_connector,
        target_type=req.target_connector,
        operations=_live_recipe_operations(req.operations),
        business_key=[],  # keeps _apply_value_mappings from running inside this call
        value_mappings=[],
        aggregation_rules=[],
        compare_fields=[],
        source_schema=req.source_schema,
        target_schema=req.target_schema,
    )

    try:
        built = build_shadow_source(draft, source_df)
    except Exception as exc:  # noqa: BLE001 — a mid-edit recipe must never 500 the live pre-pass
        raise HTTPException(status_code=400, detail=f"Recipe could not be previewed: {exc}")
    shadow_df = built.shadow_df

    def _pair_fn(**kwargs: Any) -> Any:
        return pair_values_deterministic_only(
            source_connector=req.source_connector,
            target_connector=req.target_connector,
            **kwargs,
        )

    mappings = run_key_pairs(req.key_pairs, shadow_df, target_df, "Recipe output", _pair_fn)
    return {"pairs": [m.model_dump(mode="json") for m in mappings]}
