"""The calculated-column safe expression evaluator — accept the allow-list,
reject everything else. This is the one place the engine takes a free-form
expression, so the rejection cases are the important ones."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.recon_engine.operations import safe_expr as se


COLUMNS = ["PLNMG", "DEMANDQTY", "QTY"]


@pytest.mark.parametrize(
    "expr",
    [
        "ABS(PLNMG - DEMANDQTY)",
        "PLNMG + DEMANDQTY * 2",
        "ROUND(PLNMG / 3, 2)",
        "MIN(PLNMG, DEMANDQTY, 5)",
        "MAX(PLNMG, DEMANDQTY)",
        "FLOOR(PLNMG / 2)",
        "CEIL(QTY / 7)",
        "(PLNMG - DEMANDQTY) % 4",
        "PLNMG > DEMANDQTY",
        "-PLNMG + 10",
        "42",
    ],
)
def test_accepts_allow_listed_expressions(expr):
    assert se.validate_expression(expr, COLUMNS) == []


@pytest.mark.parametrize(
    "expr",
    [
        '__import__("os").system("echo hi")',
        "os.system('x')",
        "PLNMG.__class__",
        "PLNMG.values",
        "foo(PLNMG)",              # unknown function
        "eval('1')",              # unknown function
        "UNKNOWN_COLUMN + 1",     # unknown identifier
        "PLNMG ** 8",             # power operator removed
        "1 < PLNMG < 100",        # chained comparison
        "lambda x: x",
        "[c for c in PLNMG]",
        "PLNMG if QTY else 0",    # conditional expression
        "'a string'",            # non-numeric literal
        "PLNMG[0]",               # subscript
        "",                        # empty
        "PLNMG +",                # syntax error
    ],
)
def test_rejects_everything_outside_allow_list(expr):
    errors = se.validate_expression(expr, COLUMNS)
    assert errors, f"expected {expr!r} to be rejected"


def test_eval_matches_pandas_semantics():
    df = pd.DataFrame({"PLNMG": [10, 20, 5], "DEMANDQTY": [3, 25, 5], "QTY": [12, 0, 7]})
    out = se.eval_expression("ABS(PLNMG - DEMANDQTY)", df)
    assert out.tolist() == [7, 5, 0]
    assert se.eval_expression("ROUND(PLNMG / 3, 2)", df).tolist() == [3.33, 6.67, 1.67]
    assert se.eval_expression("MIN(PLNMG, DEMANDQTY, 8)", df).tolist() == [3, 8, 5]


def test_eval_refuses_unvalidated_input_at_runtime():
    """Even if a bad expression somehow reaches eval, it raises rather than
    running arbitrary code."""
    df = pd.DataFrame({"PLNMG": [1]})
    with pytest.raises(se.ExpressionError):
        se.eval_expression('__import__("os").system("x")', df)
