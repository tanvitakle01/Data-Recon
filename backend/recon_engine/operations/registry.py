"""The allow-listed operation registry.

This is the *fixed* set of things a contract is permitted to do. The compiler's
LLM output is validated against this registry (Gate 1): any operation name not
present here, or any invalid parameters, blocks the contract. New operations
are never auto-created — a developer must add and test one here.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Any, Callable

from backend.recon_engine.operations import ops


class OperationKind(str, Enum):
    TRANSFORM = "transform"  # row-preserving column change
    FILTER = "filter"  # drops rows
    AGGREGATE = "aggregate"  # changes row cardinality / shape
    COMPARE = "compare"  # used at reconcile time, not for shadow building


@dataclass(frozen=True)
class OperationSpec:
    name: str
    kind: OperationKind
    func: Callable[..., Any]
    description: str
    requires_field: bool = True
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    # Params whose value must be a column name present in the source schema.
    field_params: tuple[str, ...] = ()
    # Params whose value must be a *list* of column names in the source schema.
    field_list_params: tuple[str, ...] = ()

    def validate(self, field: str | None, params: dict[str, Any], columns: list[str]) -> list[str]:
        """Return a list of human-readable validation errors (empty == valid)."""
        errors: list[str] = []
        colset = set(columns)

        if self.requires_field:
            if not field:
                errors.append(f"operation '{self.name}' requires a 'field'.")
            elif field not in colset:
                errors.append(
                    f"operation '{self.name}' references unknown field '{field}'."
                )

        for req in self.required_params:
            if req not in params:
                errors.append(f"operation '{self.name}' missing required param '{req}'.")

        allowed = set(self.required_params) | set(self.optional_params)
        for key in params:
            if key not in allowed:
                errors.append(f"operation '{self.name}' has unexpected param '{key}'.")

        for fp in self.field_params:
            val = params.get(fp)
            if val is not None and val not in colset:
                errors.append(
                    f"operation '{self.name}' param '{fp}'='{val}' is not a known field."
                )

        for flp in self.field_list_params:
            val = params.get(flp)
            if val is not None:
                if not isinstance(val, list):
                    errors.append(f"operation '{self.name}' param '{flp}' must be a list.")
                else:
                    for c in val:
                        if c not in colset:
                            errors.append(
                                f"operation '{self.name}' param '{flp}' references unknown field '{c}'."
                            )
        return errors


_SPECS: list[OperationSpec] = [
    OperationSpec(
        "identity_cast_string", OperationKind.TRANSFORM, ops.identity_cast_string,
        "Cast a column to string (nulls preserved).",
    ),
    OperationSpec(
        "trim_string", OperationKind.TRANSFORM, ops.trim_string,
        "Strip leading/trailing whitespace.",
    ),
    OperationSpec(
        "numeric_cast", OperationKind.TRANSFORM, ops.numeric_cast,
        "Coerce a column to numeric (unparseable -> null).",
    ),
    OperationSpec(
        "date_parse", OperationKind.TRANSFORM, ops.date_parse,
        "Parse a date column and reformat to a canonical format.",
        required_params=("source_format",),
        optional_params=("canonical_format",),
    ),
    OperationSpec(
        "rename_field", OperationKind.TRANSFORM, ops.rename_field,
        "Relabel a column WITHOUT changing its values. Never use this to modify "
        "a value (prefix/suffix/replace/etc.) — use the value-transform ops.",
        required_params=("to",),
    ),
    # ── value-transform ops (executable form of Transformation Rules) ──────────
    OperationSpec(
        "prepend_prefix", OperationKind.TRANSFORM, ops.prepend_prefix,
        "Prepend a fixed prefix to a field's value (e.g. '5006' -> 'PL5006').",
        required_params=("value",),
    ),
    OperationSpec(
        "append_suffix", OperationKind.TRANSFORM, ops.append_suffix,
        "Append a fixed suffix to a field's value (e.g. '5006' -> '5006@S21400').",
        required_params=("value",),
    ),
    OperationSpec(
        "remove_leading_zeros", OperationKind.TRANSFORM, ops.remove_leading_zeros,
        "Strip leading zeros from a field ('005006' -> '5006').",
    ),
    OperationSpec(
        "replace_value", OperationKind.TRANSFORM, ops.replace_value,
        "Literal substring replace of 'from' with 'to' ('N01-FG01' -> 'T01-FG01').",
        required_params=("from", "to"),
    ),
    OperationSpec(
        "uppercase", OperationKind.TRANSFORM, ops.uppercase,
        "Upper-case a string field.",
    ),
    OperationSpec(
        "lowercase", OperationKind.TRANSFORM, ops.lowercase,
        "Lower-case a string field.",
    ),
    OperationSpec(
        "substring", OperationKind.TRANSFORM, ops.substring,
        "Slice a value by 0-based 'start' and optional 'length'.",
        required_params=("start",),
        optional_params=("length",),
    ),
    OperationSpec(
        "regex_replace", OperationKind.TRANSFORM, ops.regex_replace,
        "Regex substitute 'pattern' with 'replacement' (deterministic; not code).",
        required_params=("pattern", "replacement"),
    ),
    OperationSpec(
        "concat_fields", OperationKind.TRANSFORM, ops.concat_fields,
        "Join several columns into 'into' with a 'separator'.",
        requires_field=False,
        required_params=("fields", "into"),
        optional_params=("separator",),
        field_list_params=("fields",),
    ),
    OperationSpec(
        "decimal_round", OperationKind.TRANSFORM, ops.decimal_round,
        "Coerce to numeric and round to 'decimals' places (default 0).",
        optional_params=("decimals",),
    ),
    OperationSpec(
        "null_to_default", OperationKind.TRANSFORM, ops.null_to_default,
        "Replace null/blank values with 'default'.",
        required_params=("default",),
    ),
    OperationSpec(
        "value_mapping", OperationKind.TRANSFORM, ops.value_mapping,
        "Whole-value lookup replacement via 'mapping'; unmapped -> 'default' or unchanged.",
        required_params=("mapping",),
        optional_params=("default",),
    ),
    OperationSpec(
        "conditional_prefix", OperationKind.TRANSFORM, ops.conditional_prefix,
        "Prepend 'value' only to rows meeting 'condition' "
        "(numeric | non_numeric | non_empty | matches+pattern).",
        required_params=("value",),
        optional_params=("condition", "pattern"),
    ),
    OperationSpec(
        "conditional_suffix", OperationKind.TRANSFORM, ops.conditional_suffix,
        "Append 'value' only to rows meeting 'condition' "
        "(numeric | non_numeric | non_empty | matches+pattern).",
        required_params=("value",),
        optional_params=("condition", "pattern"),
    ),
    OperationSpec(
        "date_format", OperationKind.TRANSFORM, ops.date_parse,
        "Alias of date_parse: parse a date and reformat to a canonical format.",
        required_params=("source_format",),
        optional_params=("canonical_format",),
    ),
    OperationSpec(
        "reject_null", OperationKind.FILTER, ops.reject_null,
        "Drop rows where the field is null/blank.",
    ),
    OperationSpec(
        "exclude_value", OperationKind.FILTER, ops.exclude_value,
        "Drop rows where the field is one of the given values.",
        required_params=("values",),
    ),
    OperationSpec(
        "include_value", OperationKind.FILTER, ops.include_value,
        "Keep only rows where the field is one of the given values "
        "(e.g. a selection filter like 'sales org = 5875').",
        required_params=("values",),
    ),
    OperationSpec(
        "group_by", OperationKind.AGGREGATE, ops.group_by,
        "Collapse to one row per unique key combination.",
        requires_field=False,
        required_params=("by",),
        field_list_params=("by",),
    ),
    OperationSpec(
        "sum_aggregate", OperationKind.AGGREGATE, ops.sum_aggregate,
        "Group by key columns and sum the field.",
        required_params=("by",),
        field_list_params=("by",),
    ),
    OperationSpec(
        "exact_match", OperationKind.COMPARE, ops.exact_match,
        "Exact (numeric or normalised string) equality.",
        requires_field=False,
        optional_params=("options",),
    ),
    OperationSpec(
        "tolerance_match", OperationKind.COMPARE, ops.tolerance_match,
        "Numeric equality within an absolute tolerance.",
        requires_field=False,
        required_params=("tolerance",),
    ),
]

REGISTRY: dict[str, OperationSpec] = {spec.name: spec for spec in _SPECS}


def list_operations() -> list[dict[str, Any]]:
    """Registry contents as plain dicts (for API / UI discovery)."""
    return [
        {
            "name": s.name,
            "kind": s.kind.value,
            "description": s.description,
            "requires_field": s.requires_field,
            "required_params": list(s.required_params),
            "optional_params": list(s.optional_params),
        }
        for s in _SPECS
    ]


def is_allowed(name: str) -> bool:
    return name in REGISTRY


def get_operation(name: str) -> OperationSpec:
    if name not in REGISTRY:
        raise KeyError(f"Operation '{name}' is not in the allow-listed registry.")
    return REGISTRY[name]
