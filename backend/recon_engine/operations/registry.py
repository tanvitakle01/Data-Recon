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
    # Params whose value must be a list of {"field": <known column>, "func":
    # <name in ops.AGGREGATE_FUNCS>} dicts — e.g. aggregate_group's multi-field,
    # multi-function aggregation spec.
    aggregation_spec_params: tuple[str, ...] = ()
    # True for an operation whose implementation reads ``params["_run_date"]``
    # — a run-time anchor the executor injects itself (never authored, never
    # part of the stored contract's params, so Gate 1 never sees or validates
    # it). See ``engine.executor.build_shadow_source``'s ``run_date`` param.
    needs_run_date: bool = False
    # Params whose value must be a column name present in the source schema
    # UNLESS it equals the mapped sentinel (e.g. relative_date_reassign's
    # "compare_to" is either a real column or the literal "run_date") — the
    # sentinel bypasses the field-existence check, anything else must resolve.
    sentinel_field_params: dict[str, str] = dc_field(default_factory=dict)
    # Params whose value, when present, must be one of a fixed set of literal
    # strings — caught here (Gate 1, before any execution) rather than only
    # surfacing as a cryptic "executor raised" failure at Gate 2 replay.
    enum_params: dict[str, frozenset[str]] = dc_field(default_factory=dict)
    # Name of the field-list param holding this operation's group-by keys
    # (e.g. aggregate_group's "by") — cross-referenced against every
    # `aggregation_spec_params` entry's "field" so a measure can never also be
    # a grouping key in the same call (grouping by a field and then
    # aggregating it is a degenerate no-op that signals the compiler confused
    # a dimension with a measure). None for operations with no group-by param.
    group_by_param: str | None = None

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

        group_fields: set[Any] = set()
        if self.group_by_param:
            by_val = params.get(self.group_by_param)
            if isinstance(by_val, list):
                group_fields = set(by_val)

        for asp in self.aggregation_spec_params:
            val = params.get(asp)
            if val is None:
                continue
            if not isinstance(val, list) or not val:
                errors.append(f"operation '{self.name}' param '{asp}' must be a non-empty list.")
                continue
            for item in val:
                if not isinstance(item, dict):
                    errors.append(
                        f"operation '{self.name}' param '{asp}' entries must be objects with 'field' and 'func'."
                    )
                    continue
                measure_field = item.get("field")
                if measure_field not in colset:
                    errors.append(
                        f"operation '{self.name}' param '{asp}' references unknown field '{measure_field}'."
                    )
                if item.get("func") not in ops.AGGREGATE_FUNCS:
                    errors.append(
                        f"operation '{self.name}' param '{asp}' has unknown func '{item.get('func')}'."
                    )
                if measure_field in group_fields:
                    errors.append(
                        f"operation '{self.name}' param '{asp}' field '{measure_field}' is also a "
                        f"'{self.group_by_param}' key — a field cannot be both a group-by dimension "
                        f"and an aggregated measure in the same call."
                    )

        for sfp, sentinel in self.sentinel_field_params.items():
            val = params.get(sfp)
            if val is not None and val != sentinel and val not in colset:
                errors.append(
                    f"operation '{self.name}' param '{sfp}'='{val}' is not a known field "
                    f"(or the literal '{sentinel}')."
                )

        for ep, allowed_values in self.enum_params.items():
            val = params.get(ep)
            if val is not None and val not in allowed_values:
                errors.append(
                    f"operation '{self.name}' param '{ep}'='{val}' must be one of "
                    f"{sorted(allowed_values)}."
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
        "Strip leading zeros from the embedded numeric run in a field's value "
        "('005006' -> '5006', 'FG0006' -> 'FG6'); optional 'min_width' floors "
        "how far it strips (e.g. min_width=2: 'FG0006' -> 'FG06').",
        optional_params=("min_width",),
    ),
    OperationSpec(
        "pad_leading_zeros", OperationKind.TRANSFORM, ops.pad_leading_zeros,
        "Left-pad the embedded numeric run in a field's value with zeros to "
        "'width' ('5006' -> '005006' at width=6). Inverse of "
        "remove_leading_zeros.",
        required_params=("width",),
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
        "date_bucket", OperationKind.TRANSFORM, ops.date_bucket,
        "Floor/ceil a date field to a period boundary ('start' or 'end' of "
        "day/week/month/quarter/year), emitting canonical YYYY-MM-DD. The "
        "general, standalone form of period bucketing — use this instead of "
        "the structured aggregation_rules group_by_* family when the "
        "bucketed date is needed as an ordinary value (e.g. before a filter "
        "or comparison), not as an aggregation's grouping key.",
        required_params=("granularity",),
        optional_params=("anchor",),
        enum_params={
            "granularity": frozenset({"day", "week", "month", "quarter", "year"}),
            "anchor": frozenset({"start", "end"}),
        },
    ),
    OperationSpec(
        "relative_date_reassign", OperationKind.TRANSFORM, ops.relative_date_reassign,
        "Replace a date with an offset from the run-time anchor (run_date) "
        "when a condition holds, else pass it through unchanged — e.g. "
        "'roll a past-due date forward by 1 day, or by 2 on a Saturday "
        "run_date'. 'date_condition' (lt|gt|eq) compares the field against "
        "'compare_to' (run_date, the default, or another field). "
        "'weekday_exception' overrides 'offset_days' when run_date itself "
        "falls on a given weekday.",
        required_params=("date_condition", "offset_days"),
        optional_params=("compare_to", "weekday_exception"),
        needs_run_date=True,
        sentinel_field_params={"compare_to": "run_date"},
        enum_params={"date_condition": frozenset({"lt", "gt", "eq"})},
    ),
    OperationSpec(
        "split_field", OperationKind.TRANSFORM, ops.split_field,
        "Split a value on 'separator' and keep the part at 0-based 'index', "
        "writing to 'into' (new column, defaults to the field itself).",
        required_params=("separator", "index"),
        optional_params=("into",),
    ),
    OperationSpec(
        "convert_uom", OperationKind.TRANSFORM, ops.convert_uom,
        "Convert a numeric field's unit by a fixed 'factor' via 'operation' "
        "('multiply' default or 'divide'), optionally rounded to 'decimals'.",
        required_params=("factor",),
        optional_params=("operation", "decimals"),
    ),
    OperationSpec(
        "calculated_column", OperationKind.TRANSFORM, ops.calculated_column,
        "Compute a new column 'into' from a safe, allow-listed 'expression' "
        "(e.g. 'ABS(PLNMG - DEMANDQTY)'). Parsed to an AST and evaluated "
        "deterministically — never executable code. See operations.safe_expr.",
        requires_field=False,
        required_params=("expression", "into"),
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
        "date_window_filter", OperationKind.FILTER, ops.date_window_filter,
        "Keep rows whose date field falls within an offset window of the "
        "run-time anchor (run_date): [run_date + lower_offset_days, run_date "
        "+ upper_offset_days]. Either bound may be omitted for an open-ended "
        "window (e.g. 'past 90 days to any future date'). Unlike "
        "exclude_value/include_value (literal values), this filters relative "
        "to when the run executes, not a fixed date.",
        optional_params=("lower_offset_days", "upper_offset_days"),
        needs_run_date=True,
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
        "deduplicate", OperationKind.AGGREGATE, ops.deduplicate,
        "Drop duplicate rows keyed on 'by', keeping 'keep' ('first' default or "
        "'last').",
        requires_field=False,
        required_params=("by",),
        optional_params=("keep",),
        field_list_params=("by",),
    ),
    OperationSpec(
        "aggregate_group", OperationKind.AGGREGATE, ops.aggregate_group,
        "Group by ANY NUMBER of columns and apply ANY NUMBER of aggregations "
        "(sum/count/average/min/max/first) in a single step — combines Group "
        "By + Aggregate. Use this ONE primitive for every multi-key, "
        "multi-measure aggregation (e.g. group by product+plant+customer+"
        "month while summing quantity and averaging price) — never split "
        "into several single-field aggregate calls. Lineage to every "
        "contributing raw source row is preserved automatically by the "
        "executor for this (and every other) AGGREGATE operation. A field "
        "in 'by' can never also appear in 'aggregations' — a group-by "
        "dimension and an aggregated measure are mutually exclusive.",
        requires_field=False,
        required_params=("by", "aggregations"),
        field_list_params=("by",),
        aggregation_spec_params=("aggregations",),
        group_by_param="by",
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
