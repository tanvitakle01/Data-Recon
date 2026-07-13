"""Validation Gate 1 — structural.

Checks, before any approval:
  * valid contract schema (Pydantic parse)
  * every operation name is in the allow-listed registry
  * every operation's params are valid for that operation
  * every referenced field exists in the *actual* source/target schema
    (no assumed fields — schemas come from the connectors / uploaded files)

Any failure blocks approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from backend.recon_engine.models.contract import DraftContract, TransformationContract
from backend.recon_engine.operations import is_allowed, get_operation


@dataclass
class Gate1Report:
    ok: bool
    errors: list[str] = field(default_factory=list)
    # Positive, business-friendly confirmations surfaced to the user alongside a
    # passing check.
    info: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"gate": "structural", "ok": self.ok, "errors": self.errors, "info": self.info}


def _coerce_contract(contract: Any) -> tuple[Any, list[str]]:
    """Accept a model or raw dict; return (contract_or_None, schema_errors)."""
    if isinstance(contract, (DraftContract, TransformationContract)):
        return contract, []
    try:
        return DraftContract.model_validate(contract), []
    except ValidationError as exc:
        return None, [f"schema: {e['loc']}: {e['msg']}" for e in exc.errors()]


def validate_structural(
    contract: Any,
    source_columns: list[str],
    target_columns: list[str],
) -> Gate1Report:
    parsed, schema_errors = _coerce_contract(contract)
    if parsed is None:
        return Gate1Report(ok=False, errors=schema_errors)

    errors: list[str] = []
    info: list[str] = []
    tgt_set = set(target_columns)

    # Track columns as they would exist after each op (rename adds/removes).
    live_columns = list(source_columns)

    # ── operations ───────────────────────────────────────────────────────────
    for op in parsed.operations:
        if not is_allowed(op.op):
            errors.append(f"operation '{op.op}' is not in the allow-listed registry.")
            continue
        spec = get_operation(op.op)
        errors.extend(spec.validate(op.field, op.params, live_columns))

        # Reflect column-shape changes so later ops — and the business-key /
        # compare-field survival checks below — validate against the schema as
        # it actually exists AFTER the operation runs.
        if op.op == "rename_field" and op.field in live_columns and "to" in op.params:
            # A rename removes the old name and adds the new one.
            live_columns = [op.params["to"] if c == op.field else c for c in live_columns]
        elif op.op == "concat_fields":
            # concat_fields writes into a (possibly new) 'into' column.
            into = op.params.get("into")
            if into and into not in live_columns:
                live_columns = [*live_columns, into]

    # ── business key ─────────────────────────────────────────────────────────
    # Rule: business-key fields must still exist in the shadow AFTER all ops.
    # We therefore validate against ``live_columns`` (the post-transformation
    # schema), not the raw source — so a key that was renamed/dropped away is
    # caught here rather than blowing up at reconcile time.
    if not parsed.business_key:
        errors.append("No matching key defined; at least one key field is required.")
    for bk in parsed.business_key:
        if bk.source_field not in live_columns:
            errors.append(
                f"business_key source field '{bk.source_field}' does not exist after "
                "operations run (was it renamed or dropped?); business keys must survive "
                "transformation."
            )
        if bk.target_field not in tgt_set:
            errors.append(f"business_key target field '{bk.target_field}' not in target schema.")

    # ── compare fields ─────────────────────────────────────────────────────
    for cf in parsed.compare_fields:
        if cf.source_field not in live_columns:
            errors.append(
                f"compare source field '{cf.source_field}' does not exist after operations run."
            )
        if cf.target_field not in tgt_set:
            errors.append(f"compare target field '{cf.target_field}' not in target schema.")

    # ── aggregation rules ────────────────────────────────────────────────────
    # Applied after transforms, so the field must exist in the post-transform
    # schema (period buckets edit the field in place; measures aggregate it).
    for rule in getattr(parsed, "aggregation_rules", []):
        if rule.source_field not in live_columns:
            errors.append(
                f"aggregation rule field '{rule.source_field}' does not exist after "
                "operations run; cannot aggregate a missing field."
            )

    return Gate1Report(ok=not errors, errors=errors, info=info)
