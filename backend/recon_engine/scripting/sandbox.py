"""Sandboxed execution of validated transformation scripts.

Execution happens in a restricted namespace: a minimal builtins allow-list, a
guarded ``__import__`` limited to :data:`~.validator.ALLOWED_IMPORTS`, and
pre-injected ``pd``/``np``/``math``/``re``/``datetime``. Scripts must already
have passed :func:`~.validator.validate_script` — the sandbox re-checks this
and refuses to run anything that fails static validation.

Note on isolation: this is an in-process restricted namespace (plus the AST
gate), not OS-level isolation. The layered gates are: static validation →
sandbox namespace → human approval of the *data* → hash-pinned production
execution.

Besides running the script, this module computes the business-facing diff
between input and output: renamed/added/removed/modified columns, affected
row count, and row-level before/after diffs for the preview UI.
"""

from __future__ import annotations

import datetime as _datetime
import math as _math
import re as _re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.recon_engine.scripting.validator import ALLOWED_IMPORTS, ENTRYPOINT, validate_script


class ScriptExecutionError(RuntimeError):
    """Raised when a script cannot be executed or misbehaves at runtime."""


_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "int", "isinstance", "issubclass", "len",
    "list", "map", "max", "min", "pow", "range", "repr", "reversed", "round",
    "set", "slice", "sorted", "str", "sum", "tuple", "zip",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "ZeroDivisionError", "ArithmeticError", "AttributeError", "StopIteration",
    "True", "False", "None",
)


def _guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
    root = name.split(".")[0]
    if root not in ALLOWED_IMPORTS:
        raise ImportError(f"Import of '{name}' is not allowed in transformation scripts.")
    return __import__(name, *args, **kwargs)


def _build_namespace(log: list[str]) -> dict[str, Any]:
    import builtins as _builtins

    safe_builtins: dict[str, Any] = {
        n: getattr(_builtins, n) for n in _SAFE_BUILTIN_NAMES if hasattr(_builtins, n)
    }
    safe_builtins["__import__"] = _guarded_import
    safe_builtins["print"] = lambda *a, **k: log.append(" ".join(str(x) for x in a))
    return {
        "__builtins__": safe_builtins,
        "pd": pd,
        "np": np,
        "math": _math,
        "re": _re,
        "datetime": _datetime,
    }


@dataclass
class SandboxResult:
    transformed_df: pd.DataFrame
    modified_columns: list[dict[str, Any]]
    affected_rows: int
    row_diffs: list[dict[str, Any]]
    execution_log: list[str] = field(default_factory=list)


def _cell(value: Any) -> Any:
    """JSON-safe scalar for diff payloads."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def _series_equal(a: pd.Series, b: pd.Series) -> pd.Series:
    """Element-wise equality treating NaN==NaN, compared as strings."""
    a_s = a.reset_index(drop=True).map(_cell).map(lambda v: "" if v is None else str(v))
    b_s = b.reset_index(drop=True).map(_cell).map(lambda v: "" if v is None else str(v))
    return a_s == b_s


def compute_diff(
    original: pd.DataFrame, transformed: pd.DataFrame, *, max_row_diffs: int = 50
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """Business-facing change report: (modified_columns, affected_rows, row_diffs).

    Renames are detected value-wise (a removed column whose values equal an
    added column's) so the preview can say "MATNR → PRDID" instead of showing
    a drop + an add.
    """
    orig_cols = [str(c) for c in original.columns]
    new_cols = [str(c) for c in transformed.columns]
    removed = [c for c in orig_cols if c not in new_cols]
    added = [c for c in new_cols if c not in orig_cols]
    common = [c for c in orig_cols if c in new_cols]

    same_len = len(original) == len(transformed)

    # Pair original -> transformed columns. Common names pair with themselves;
    # removed/added columns pair as renames — first by identical values, then
    # positionally (a rename whose values also changed, e.g. MATNR -> PRDID
    # with zeros stripped in the same step).
    pairs: list[tuple[str, str]] = [(c, c) for c in common]
    if same_len:
        for old in list(removed):
            for new in list(added):
                if _series_equal(original[old], transformed[new]).all():
                    pairs.append((old, new))
                    removed.remove(old)
                    added.remove(new)
                    break
    for old, new in zip(list(removed), list(added)):
        pairs.append((old, new))
        removed.remove(old)
        added.remove(new)

    modified_columns: list[dict[str, Any]] = []
    changed_mask = pd.Series([False] * min(len(original), len(transformed)))
    changed_pairs: list[tuple[str, str]] = []

    for src_col, out_col in pairs:
        changed = False
        if same_len and len(original) > 0:
            eq = _series_equal(original[src_col], transformed[out_col])
            changed = not bool(eq.all())
            if changed:
                changed_mask = changed_mask | ~eq
                changed_pairs.append((src_col, out_col))
        if src_col != out_col:
            entry: dict[str, Any] = {
                "column": out_col,
                "change": "modified" if changed else "renamed",
                "from": src_col,
            }
            modified_columns.append(entry)
        elif changed:
            modified_columns.append({"column": out_col, "change": "modified"})

    for c in added:
        modified_columns.append({"column": c, "change": "added"})
    for c in removed:
        modified_columns.append({"column": c, "change": "removed"})

    if same_len:
        affected_rows = int(changed_mask.sum())
    else:
        # Row count changed (filters/aggregation): report the row delta.
        affected_rows = int(abs(len(original) - len(transformed)))

    # Row-level before/after diffs for the preview UI.
    row_diffs: list[dict[str, Any]] = []
    if same_len and changed_pairs:
        orig_reset = original.reset_index(drop=True)
        new_reset = transformed.reset_index(drop=True)
        diff_indices = changed_mask[changed_mask].index[:max_row_diffs]
        for idx in diff_indices:
            changes = []
            for src_col, out_col in changed_pairs:
                before = _cell(orig_reset.at[idx, src_col])
                after = _cell(new_reset.at[idx, out_col])
                b = "" if before is None else str(before)
                a = "" if after is None else str(after)
                if b != a:
                    changes.append({"column": out_col, "before": before, "after": after})
            if changes:
                row_diffs.append({"row_index": int(idx), "changes": changes})

    return modified_columns, affected_rows, row_diffs


def execute_script(
    script_text: str, df: pd.DataFrame, *, max_row_diffs: int = 50
) -> SandboxResult:
    """Validate, execute in the restricted namespace, and diff the result."""
    report = validate_script(script_text)
    if not report.ok:
        raise ScriptExecutionError(
            "Script failed static validation: " + "; ".join(report.errors)
        )

    log: list[str] = []
    namespace = _build_namespace(log)
    try:
        exec(compile(script_text, "<transformation_script>", "exec"), namespace)  # noqa: S102
    except Exception as exc:  # noqa: BLE001 - surfaced as a controlled error
        raise ScriptExecutionError(f"Script failed to load: {exc}") from exc

    fn = namespace.get(ENTRYPOINT)
    if not callable(fn):
        raise ScriptExecutionError(f"Script did not define a callable `{ENTRYPOINT}`.")

    original = df.copy(deep=True)
    try:
        result = fn(df.copy(deep=True))
    except Exception as exc:  # noqa: BLE001 - surfaced as a controlled error
        raise ScriptExecutionError(f"Script raised during execution: {exc}") from exc

    if not isinstance(result, pd.DataFrame):
        raise ScriptExecutionError(
            f"`{ENTRYPOINT}` must return a pandas DataFrame, got {type(result).__name__}."
        )
    if result.empty and not original.empty:
        raise ScriptExecutionError(
            "Transformation produced an empty dataframe from non-empty input."
        )

    modified_columns, affected_rows, row_diffs = compute_diff(
        original, result, max_row_diffs=max_row_diffs
    )
    log.append(
        f"Executed `{ENTRYPOINT}`: {len(original)} rows in → {len(result)} rows out; "
        f"{len(modified_columns)} column change(s); {affected_rows} row(s) affected."
    )
    return SandboxResult(
        transformed_df=result,
        modified_columns=modified_columns,
        affected_rows=affected_rows,
        row_diffs=row_diffs,
        execution_log=log,
    )
