"""Step-recipe authoring proofs (Phase 3).

The recipe editor authors the SAME `operations` array the manual flow compiles,
so these tests exercise it at the contract/executor level:

  * the four new ops behave and validate through Gate 1;
  * a disabled step is completely inert (executor + Gate 1);
  * visible order == execution order (Decision B): cross-phase authored order
    never changes execution, within-phase order always does;
  * the draft/per-step preview truncates at the active step;
  * a recipe-authored contract reconciles IDENTICALLY to the equivalent
    stub-compiled contract (same array in, same behaviour out).
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine import service
from backend.recon_engine.compiler.stub_compiler import StubContractCompiler
from backend.recon_engine.engine import build_shadow_source, reconcile, shadow_fingerprint
from backend.recon_engine.engine.executor import LINEAGE_COL
from backend.recon_engine.models.contract import (
    BusinessKeyField,
    CompareField,
    ContractOperation,
    DraftContract,
    MatchType,
)
from backend.recon_engine.models.rules import BusinessRule, BusinessRules
from backend.recon_engine.operations import get_operation, is_allowed
from backend.recon_engine.validation.gate1_structural import validate_structural


def _draft(operations, columns, **kw):
    return DraftContract(
        comparison_type="t",
        source_type="excel",
        target_type="excel",
        operations=operations,
        source_schema=list(columns),
        target_schema=list(columns),
        **kw,
    )


# ── new ops: behaviour ───────────────────────────────────────────────────────

def test_split_field_into_new_column():
    from backend.recon_engine.operations import ops

    df = pd.DataFrame({"m": ["A-01", "B-02", None]}, dtype=object)
    out = ops.split_field(df, "m", {"separator": "-", "index": 0, "into": "root"})
    assert out["root"].tolist()[:2] == ["A", "B"]
    assert pd.isna(out["root"].iloc[2])


def test_convert_uom_multiply_and_divide():
    from backend.recon_engine.operations import ops

    df = pd.DataFrame({"q": ["12", "24", "nope"]})
    mult = ops.convert_uom(df, "q", {"factor": 2})
    assert mult["q"].iloc[0] == 24.0
    div = ops.convert_uom(df, "q", {"factor": 12, "operation": "divide"})
    assert div["q"].tolist()[:2] == [1.0, 2.0]
    assert pd.isna(div["q"].iloc[2])


def test_deduplicate_keeps_first_and_last():
    from backend.recon_engine.operations import ops

    df = pd.DataFrame({"k": ["x", "x", "y"], "v": [1, 2, 3]})
    first = ops.deduplicate(df, None, {"by": ["k"]})
    assert first["v"].tolist() == [1, 3]
    last = ops.deduplicate(df, None, {"by": ["k"], "keep": "last"})
    assert last["v"].tolist() == [2, 3]


def test_calculated_column_via_executor():
    ops_list = [
        ContractOperation(op="calculated_column", params={"expression": "ABS(a - b)", "into": "var"})
    ]
    c = _draft(ops_list, ["a", "b"], business_key=[BusinessKeyField(source_field="a", target_field="a")])
    built = build_shadow_source(c, pd.DataFrame({"a": [10, 5], "b": [3, 5]}))
    assert built.shadow_df["var"].tolist() == [7, 0]


# ── Gate 1: membership + params + expression ────────────────────────────────

def test_new_ops_are_allow_listed():
    for name in ("split_field", "convert_uom", "deduplicate", "calculated_column"):
        assert is_allowed(name)
        assert get_operation(name).name == name


def test_gate1_accepts_valid_new_ops():
    ops_list = [
        ContractOperation(op="split_field", field="m", params={"separator": "-", "index": 0, "into": "root"}),
        ContractOperation(op="convert_uom", field="q", params={"factor": 12, "operation": "divide"}),
        ContractOperation(op="calculated_column", params={"expression": "ABS(a - b)", "into": "var"}),
        ContractOperation(op="deduplicate", params={"by": ["m"]}),
    ]
    cols = ["m", "q", "a", "b"]
    c = _draft(ops_list, cols, business_key=[BusinessKeyField(source_field="m", target_field="m")])
    report = validate_structural(c, cols, cols)
    assert report.ok, report.errors


def test_gate1_rejects_bad_expression_and_unknown_split_param():
    ops_list = [
        ContractOperation(op="calculated_column", params={"expression": "danger(a)", "into": "x"}),
        ContractOperation(op="split_field", field="m", params={"separator": "-", "index": 0, "junk": 1}),
    ]
    cols = ["m", "a"]
    c = _draft(ops_list, cols, business_key=[BusinessKeyField(source_field="m", target_field="m")])
    report = validate_structural(c, cols, cols)
    assert not report.ok
    joined = " ".join(report.errors)
    assert "calculated_column" in joined and "unexpected param 'junk'" in joined


def test_gate1_calculated_column_can_reference_earlier_computed_column():
    # var1 is created by step 1, then referenced by step 2 — Gate 1 must see it.
    ops_list = [
        ContractOperation(op="calculated_column", params={"expression": "a + b", "into": "var1"}),
        ContractOperation(op="calculated_column", params={"expression": "var1 * 2", "into": "var2"}),
    ]
    cols = ["a", "b"]
    c = _draft(ops_list, cols, business_key=[BusinessKeyField(source_field="a", target_field="a")])
    assert validate_structural(c, cols, cols).ok


# ── disabled step is inert ──────────────────────────────────────────────────

def test_disabled_step_skipped_by_executor_and_gate1():
    cols = ["a", "b"]
    # A disabled op referencing a bogus column must NOT fail Gate 1 nor run.
    ops_list = [
        ContractOperation(op="calculated_column", enabled=False,
                          params={"expression": "NONEXISTENT + 1", "into": "ghost"}),
        ContractOperation(op="calculated_column", params={"expression": "a + b", "into": "sum"}),
    ]
    c = _draft(ops_list, cols, business_key=[BusinessKeyField(source_field="a", target_field="a")])
    assert validate_structural(c, cols, cols).ok
    built = build_shadow_source(c, pd.DataFrame({"a": [1], "b": [2]}))
    assert "ghost" not in built.shadow_df.columns
    assert built.shadow_df["sum"].tolist() == [3]


# ── Decision B: visible order == execution order ────────────────────────────

def test_cross_phase_authored_order_does_not_change_execution():
    """A transform authored AFTER an aggregate still executes in the Transform
    phase (before aggregation) — so the two authorings are byte-identical. This
    is exactly why the UI must present steps grouped by phase."""
    df = pd.DataFrame({"k": ["x", "x"], "v": ["10", "20"]})
    key = [BusinessKeyField(source_field="k", target_field="k")]

    transform_first = _draft([
        ContractOperation(op="numeric_cast", field="v"),
        ContractOperation(op="sum_aggregate", field="v", params={"by": ["k"]}),
    ], ["k", "v"], business_key=key)
    aggregate_first = _draft([
        ContractOperation(op="sum_aggregate", field="v", params={"by": ["k"]}),
        ContractOperation(op="numeric_cast", field="v"),
    ], ["k", "v"], business_key=key)

    fp1 = shadow_fingerprint(build_shadow_source(transform_first, df).shadow_df)
    fp2 = shadow_fingerprint(build_shadow_source(aggregate_first, df).shadow_df)
    assert fp1 == fp2  # cross-phase order is irrelevant to execution


def test_within_phase_order_matters_for_dependent_ops():
    df = pd.DataFrame({"p": ["005006"]})
    key = [BusinessKeyField(source_field="p", target_field="p")]
    # remove-zeros THEN prefix  -> "PL5006"; prefix THEN remove-zeros -> "PL5006" too,
    # so use replace which is genuinely order-sensitive.
    a = _draft([
        ContractOperation(op="prepend_prefix", field="p", params={"value": "0"}),
        ContractOperation(op="remove_leading_zeros", field="p"),
    ], ["p"], business_key=key)
    b = _draft([
        ContractOperation(op="remove_leading_zeros", field="p"),
        ContractOperation(op="prepend_prefix", field="p", params={"value": "0"}),
    ], ["p"], business_key=key)
    out_a = build_shadow_source(a, df).shadow_df["p"].iloc[0]
    out_b = build_shadow_source(b, df).shadow_df["p"].iloc[0]
    assert out_a == "5006"      # prepend 0 -> 0005006 -> strip -> 5006
    assert out_b == "05006"     # strip -> 5006 -> prepend 0 -> 05006
    assert out_a != out_b       # within-phase order changed the result


# ── per-step preview ────────────────────────────────────────────────────────

def test_recipe_preview_truncates_at_active_step():
    draft = {
        "comparison_type": "t", "source_type": "excel", "target_type": "excel",
        "operations": [
            {"op": "remove_leading_zeros", "field": "Plant"},
            {"op": "calculated_column", "params": {"expression": "PLNMG - DEMANDQTY", "into": "Var"}},
            {"op": "deduplicate", "params": {"by": ["Plant"]}},
        ],
        "source_schema": ["Plant", "PLNMG", "DEMANDQTY"], "target_schema": ["Plant"],
    }
    rows = [
        {"Plant": "005006", "PLNMG": 10, "DEMANDQTY": 3},
        {"Plant": "005006", "PLNMG": 10, "DEMANDQTY": 3},
        {"Plant": "001000", "PLNMG": 7, "DEMANDQTY": 7},
    ]
    full = service.build_recipe_preview(draft=draft, source_rows=rows)
    assert full["shadow"]["total_rows"] == 2            # deduped
    assert "Var" in full["shadow"]["columns"]

    step0 = service.build_recipe_preview(draft=draft, source_rows=rows, active_step_index=0)
    assert step0["shadow"]["total_rows"] == 3           # no dedup yet
    assert "Var" not in step0["shadow"]["columns"]      # calc step not reached
    assert step0["affected_columns"] == ["Plant"]


# ── equivalence: recipe-authored == stub-compiled ──────────────────────────

def test_recipe_authored_contract_reconciles_identically_to_stub_compiled():
    cols = ["Plant", "Qty"]
    source = pd.DataFrame({"Plant": ["005006", "001000"], "Qty": ["10", "20"]})
    target = pd.DataFrame({"Plant": ["5006", "1000"], "Qty": ["10", "20"]})

    key = [BusinessKeyField(source_field="Plant", target_field="Plant")]
    compare = [CompareField(source_field="Qty", target_field="Qty", match_type=MatchType.EXACT)]

    # (1) authored directly in the recipe editor
    recipe = _draft(
        [ContractOperation(op="remove_leading_zeros", field="Plant")],
        cols, business_key=key, compare_fields=compare,
    )

    # (2) the stub compiler translating the equivalent business rule
    stub = StubContractCompiler().compile(
        mapping_sheet=[{"source_col": "Plant", "target_col": "Plant"}],
        rules="",
        business_rules=BusinessRules(
            transformation_rules=[BusinessRule(field="Plant", instruction="remove leading zeros")]
        ),
        source_schema=cols, target_schema=cols,
        comparison_type="t", source_type="excel", target_type="excel",
    )
    stub = stub.model_copy(update={"business_key": key, "compare_fields": compare})

    # Same operations array...
    assert [(o.op, o.field) for o in recipe.operations] == [(o.op, o.field) for o in stub.operations]

    # ...same shadow fingerprint...
    s_recipe = build_shadow_source(recipe, source)
    s_stub = build_shadow_source(stub, source)
    assert shadow_fingerprint(s_recipe.shadow_df) == shadow_fingerprint(s_stub.shadow_df)

    # ...and identical reconciliation.
    r_recipe = reconcile(recipe, s_recipe.shadow_df, target)
    r_stub = reconcile(stub, s_stub.shadow_df, target)
    assert r_recipe.summary.model_dump() == r_stub.summary.model_dump()
    assert r_recipe.summary.match == 2
