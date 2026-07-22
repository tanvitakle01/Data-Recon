"""A safe, allow-listed arithmetic expression evaluator for calculated columns.

This is the ONE place in the engine that accepts a user-authored expression
(e.g. ``ABS(PLNMG - DEMANDQTY)``). The project's hard rule is that a contract's
inputs are DATA, never executable code — so this module never uses Python
``eval``/``exec`` or ``pandas.eval``. Instead it:

  1. Parses the expression with :mod:`ast` into a syntax tree.
  2. Walks the tree and REJECTS any node that isn't on a tiny allow-list —
     numbers, column names, ``+ - * / %``, unary ``+/-``, parentheses,
     comparisons, and a fixed set of named functions (ABS, ROUND, MIN, MAX,
     FLOOR, CEIL). Anything else — attribute access, subscripting, calls to
     unknown names, lambdas, comprehensions, dunder names, imports — is a
     validation error, not an execution.
  3. Evaluates the validated tree against a DataFrame using vectorised pandas
     operations, driven purely by the tree's shape.

Validation and evaluation share the same walker, so a value that passes
:func:`validate_expression` is exactly what :func:`eval_expression` will run —
there is no second, looser parser. Identifiers must resolve to real columns;
an unknown column is a validation error (mirrors Gate 1's field checks).
"""

from __future__ import annotations

import ast
from typing import Any

import numpy as np
import pandas as pd

# Allow-listed named functions. Each maps to a hand-written implementation that
# operates elementwise on pandas Series / scalars. NEVER extend this with
# anything that can reach the filesystem, network, or arbitrary attributes.
_FUNCTIONS = {"ABS", "ROUND", "MIN", "MAX", "FLOOR", "CEIL"}

# The only ast node types permitted anywhere in the tree.
_ALLOWED_NODES: tuple[type, ...] = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    # operators (no ** — unneeded here and a DoS vector via huge exponents)
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.USub, ast.UAdd,
    # comparisons
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)


class ExpressionError(ValueError):
    """A calculated-column expression that is empty, unparseable, or contains
    a construct outside the allow-list."""


def _collect_errors(node: ast.AST, columns: set[str], errors: list[str]) -> None:
    """Recursively validate ``node``, appending human-readable errors."""
    if not isinstance(node, _ALLOWED_NODES):
        errors.append(
            f"expression contains a disallowed construct: {type(node).__name__}."
        )
        # Don't descend into an already-rejected node — its children are moot.
        return

    if isinstance(node, ast.Name):
        # A bare name is a column reference. Reject dunder-style names outright
        # (defence in depth — they can never be valid column identifiers here).
        if node.id.startswith("__"):
            errors.append(f"expression references a disallowed name '{node.id}'.")
        elif node.id not in columns:
            errors.append(f"expression references unknown column '{node.id}'.")
        return

    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            errors.append("expression may only contain numeric literals.")
        return

    if isinstance(node, ast.Compare):
        # Single comparison only — chained forms like ``a < b < c`` are
        # ambiguous here and the evaluator handles one operator, so reject them.
        if len(node.ops) != 1:
            errors.append("chained comparisons (a < b < c) are not supported.")
        for child in ast.iter_child_nodes(node):
            _collect_errors(child, columns, errors)
        return

    if isinstance(node, ast.Call):
        # Only calls of the form NAME(args...) to an allow-listed function.
        func = node.func
        if not isinstance(func, ast.Name):
            errors.append("expression may only call named functions.")
        elif func.id not in _FUNCTIONS:
            errors.append(
                f"expression calls unknown function '{getattr(func, 'id', '?')}'. "
                f"Allowed: {', '.join(sorted(_FUNCTIONS))}."
            )
        if node.keywords:
            errors.append("expression functions do not accept keyword arguments.")
        for arg in node.args:
            _collect_errors(arg, columns, errors)
        return

    # Structural nodes: validate every child.
    for child in ast.iter_child_nodes(node):
        _collect_errors(child, columns, errors)


def _parse(expression: str) -> ast.Expression:
    text = (expression or "").strip()
    if not text:
        raise ExpressionError("expression is empty.")
    try:
        return ast.parse(text, mode="eval")
    except SyntaxError as exc:  # noqa: PERF203 - message is user-facing
        raise ExpressionError(f"expression is not valid: {exc.msg}.") from exc


def validate_expression(expression: str, columns: list[str] | set[str]) -> list[str]:
    """Return a list of validation errors (empty == valid).

    ``columns`` is the set of column names the expression is allowed to
    reference (the live post-transform schema at the point the op runs).
    """
    try:
        tree = _parse(expression)
    except ExpressionError as exc:
        return [str(exc)]
    errors: list[str] = []
    _collect_errors(tree, set(columns), errors)
    return errors


# ── evaluation (only reached for a validated tree) ──────────────────────────

def _to_numeric(value: Any) -> Any:
    if isinstance(value, pd.Series):
        return pd.to_numeric(value, errors="coerce")
    return value


_BINOPS = {
    ast.Add: lambda a, b: _to_numeric(a) + _to_numeric(b),
    ast.Sub: lambda a, b: _to_numeric(a) - _to_numeric(b),
    ast.Mult: lambda a, b: _to_numeric(a) * _to_numeric(b),
    ast.Div: lambda a, b: _to_numeric(a) / _to_numeric(b),
    ast.Mod: lambda a, b: _to_numeric(a) % _to_numeric(b),
}
_CMPOPS = {
    ast.Eq: lambda a, b: _to_numeric(a) == _to_numeric(b),
    ast.NotEq: lambda a, b: _to_numeric(a) != _to_numeric(b),
    ast.Lt: lambda a, b: _to_numeric(a) < _to_numeric(b),
    ast.LtE: lambda a, b: _to_numeric(a) <= _to_numeric(b),
    ast.Gt: lambda a, b: _to_numeric(a) > _to_numeric(b),
    ast.GtE: lambda a, b: _to_numeric(a) >= _to_numeric(b),
}


def _apply_function(name: str, args: list[Any]) -> Any:
    if name == "ABS":
        return _to_numeric(args[0]).abs() if isinstance(args[0], pd.Series) else abs(args[0])
    if name == "ROUND":
        ndigits = int(args[1]) if len(args) > 1 else 0
        val = _to_numeric(args[0])
        return val.round(ndigits) if isinstance(val, pd.Series) else round(val, ndigits)
    if name == "FLOOR":
        return np.floor(_to_numeric(args[0]))
    if name == "CEIL":
        return np.ceil(_to_numeric(args[0]))
    if name in ("MIN", "MAX"):
        # Elementwise across the argument list (columns and/or scalars).
        cols = [_to_numeric(a) for a in args]
        frame = pd.concat(
            [c if isinstance(c, pd.Series) else pd.Series(c, index=_index_of(cols)) for c in cols],
            axis=1,
        )
        return frame.min(axis=1) if name == "MIN" else frame.max(axis=1)
    raise ExpressionError(f"unknown function '{name}'.")  # unreachable post-validation


def _index_of(values: list[Any]) -> Any:
    for v in values:
        if isinstance(v, pd.Series):
            return v.index
    return None


def _eval_node(node: ast.AST, df: pd.DataFrame) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, df)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return df[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, df)
        return -_to_numeric(operand) if isinstance(node.op, ast.USub) else +_to_numeric(operand)
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, df)
        right = _eval_node(node.right, df)
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.Compare):
        # Single comparison (chained comparisons are rejected as >1 op below).
        left = _eval_node(node.left, df)
        right = _eval_node(node.comparators[0], df)
        return _CMPOPS[type(node.ops[0])](left, right)
    if isinstance(node, ast.Call):
        args = [_eval_node(a, df) for a in node.args]
        return _apply_function(node.func.id, args)
    raise ExpressionError(f"cannot evaluate node {type(node).__name__}.")  # unreachable


def eval_expression(expression: str, df: pd.DataFrame) -> pd.Series:
    """Evaluate a validated ``expression`` against ``df``, returning a Series.

    Callers MUST have validated the expression against the frame's columns
    first (via :func:`validate_expression`); this re-parses and will raise
    :class:`ExpressionError` on anything unexpected rather than trusting input.
    """
    tree = _parse(expression)
    errors: list[str] = []
    _collect_errors(tree, set(map(str, df.columns)), errors)
    if errors:
        raise ExpressionError("; ".join(errors))
    result = _eval_node(tree, df)
    if not isinstance(result, pd.Series):
        # A constant-only expression broadcasts to every row.
        result = pd.Series(result, index=df.index)
    return result
