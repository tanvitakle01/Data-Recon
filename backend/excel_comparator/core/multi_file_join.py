"""Deterministic multi-file join for the wizard's source upload slot.

Several uploaded Excel/CSV files are joined, one step at a time, into a single
combined table that the rest of the pipeline treats exactly like one uploaded
file. Pure parsing: no AI, no fuzzy matching. Every key pair is chosen
explicitly by the user (file ``i+1`` is joined onto the combined result of
files ``1..i``).

Rules, in the order they are applied:

* All files must share one type (all CSV or all Excel), 2..MAX_FILES of them.
* Non-key columns whose name appears in more than one file are suffixed
  ``_file<N>`` in every file that has them, so nothing is overwritten.
* Key *values* are matched after trimming and case-folding (and, when both key
  columns look like dates, after parsing them to ISO dates). Column names are
  never normalised.
* Rows whose key is blank never match. They stay in the result as unmatched
  when the join type keeps that side's unmatched rows (left/outer), are
  excluded otherwise, and are always reported as "missing key".
* Left rows repeated in a step's output (duplicate keys) are counted so the UI
  can warn before the result is used.
* Output keeps source file order unless a sort is requested; a date-looking
  sort key is sorted chronologically, a numeric one numerically.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePath
from typing import Any

import pandas as pd
from dateutil import parser as _dateutil

from backend.excel_comparator.core.loader import load_tabular_detailed

MAX_FILES = 5
JOIN_TYPES = ("left", "inner", "outer")

_LO = "__multi_join_left_pos__"
_RO = "__multi_join_right_pos__"
_KEY = "__multi_join_key__"
_MERGE = "__multi_join_side__"

# A string only counts as a date when its whole shape is one: a month name
# with a day/year, or three numeric parts (dots need a 4-digit year). Two-part
# values such as "12.5" or "10-20" are numbers/codes, never dates.
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_TIME = r"(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?"
_DATE_SHAPE = re.compile(
    "|".join((
        rf"\d{{1,2}}[-/. ]?{_MONTH}(?:[-/., ]+\d{{2,4}})?",
        rf"{_MONTH}[-/. ]?\d{{1,2}}(?:,?[-/. ]+\d{{2,4}})?",
        rf"{_MONTH}[-/. ]\d{{4}}",
        rf"\d{{4}}([-/.])\d{{1,2}}\1\d{{1,2}}{_TIME}",
        rf"\d{{1,2}}([-/])\d{{1,2}}\2\d{{2,4}}{_TIME}",
        rf"\d{{1,2}}\.\d{{1,2}}\.\d{{4}}{_TIME}",
    )),
    re.IGNORECASE,
)


class JoinConfigError(ValueError):
    """User-correctable problem with the files or the join configuration."""


@dataclass
class JoinStep:
    left_file: int
    left_column: str
    right_column: str
    how: str = "left"


@dataclass
class JoinSort:
    step: int
    direction: str  # "asc" | "desc"


@dataclass
class JoinResult:
    df: pd.DataFrame
    kind: str  # "csv" | "excel"
    filename: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    missing_key_groups: list[dict[str, Any]] = field(default_factory=list)
    renamed_columns: list[dict[str, Any]] = field(default_factory=list)
    sort: dict[str, Any] | None = None


# ── file type ──────────────────────────────────────────────────────────────

def file_kind(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return "csv"
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return "excel"
    raise JoinConfigError(f"Unsupported file type: {filename!r}. Upload .xlsx, .xls or .csv.")


def validate_files(filenames: list[str]) -> str:
    if len(filenames) < 2:
        raise JoinConfigError("At least two files are needed to join.")
    if len(filenames) > MAX_FILES:
        raise JoinConfigError(f"At most {MAX_FILES} files can be joined.")
    kinds = {file_kind(name) for name in filenames}
    if len(kinds) > 1:
        raise JoinConfigError("All files must be the same type — either all Excel (.xlsx/.xls) or all CSV.")
    return kinds.pop()


# ── value helpers ──────────────────────────────────────────────────────────

def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if value is pd.NaT:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_datetime_value(value: Any) -> bool:
    return isinstance(value, (_dt.datetime, _dt.date, pd.Timestamp))


# Year used for dates written without one ("2-Jan"): a leap year, so "29-Feb"
# still parses. Only relative order/equality matters for sorting and matching.
_DEFAULT_DATE = _dt.datetime(2000, 1, 1)


def _parse_date(value: Any) -> _dt.datetime | None:
    if _is_blank(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day)
    try:
        return _dateutil.parse(str(value).strip(), default=_DEFAULT_DATE)
    except (ValueError, OverflowError, TypeError):
        return None


def _iso(value: _dt.datetime) -> str:
    if value.time() == _dt.time(0, 0):
        return value.date().isoformat()
    return value.isoformat()


def looks_like_date(series: pd.Series) -> bool:
    """True when every non-blank value is a datetime, or a string with a full
    date shape (see _DATE_SHAPE) of which at least 90% parse. Plain numbers
    and two-part codes are never treated as dates."""
    values = [v for v in series.tolist() if not _is_blank(v)]
    if not values:
        return False
    if all(_is_datetime_value(v) for v in values):
        return True
    strings = [str(v).strip() for v in values if not _is_datetime_value(v)]
    if not all(_DATE_SHAPE.fullmatch(s) for s in strings):
        return False
    parsed = sum(_parse_date(s) is not None for s in strings)
    return parsed / len(strings) >= 0.9


def _normalize_key(value: Any, as_date: bool) -> Any:
    if _is_blank(value):
        return None
    if as_date or _is_datetime_value(value):
        parsed = _parse_date(value)
        if parsed is not None:
            return _iso(parsed)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip().casefold()


def _missing_mask(series: pd.Series) -> pd.Series:
    return series.map(_is_blank).astype(bool)


# ── core join ──────────────────────────────────────────────────────────────

def _collision_renames(frames: list[pd.DataFrame], steps: list[JoinStep]) -> list[dict[str, str]]:
    """Per file, {original: new} for non-key columns shared with another file.
    A file's own right-hand key column is dropped by its join step (merged into
    the left key), so it never counts as a collision."""
    dropped = {i + 1: step.right_column for i, step in enumerate(steps)}
    seen: dict[str, list[int]] = {}
    for idx, frame in enumerate(frames):
        for col in frame.columns:
            if dropped.get(idx) == col:
                continue
            seen.setdefault(col, []).append(idx)

    all_names = {col for frame in frames for col in frame.columns}
    renames: list[dict[str, str]] = [{} for _ in frames]
    for col, owners in seen.items():
        if len(owners) < 2:
            continue
        for idx in owners:
            new = f"{col}_file{idx + 1}"
            while new in all_names:
                new += "_"
            all_names.add(new)
            renames[idx][col] = new
    return renames


def _row_preview(df: pd.DataFrame, limit: int) -> list[dict[str, str]]:
    head = df.head(limit)
    return [
        {str(col): ("" if _is_blank(val) else str(val)) for col, val in row.items()}
        for row in head.to_dict(orient="records")
    ]


def _relationship(left_dups: int, right_dups: int) -> str:
    if left_dups and right_dups:
        return "many-to-many"
    if left_dups:
        return "many-to-one"
    if right_dups:
        return "one-to-many"
    return "one-to-one"


def _sort_frame(df: pd.DataFrame, column: str, direction: str) -> tuple[pd.DataFrame, str]:
    """Stable sort on one column, blanks last in either direction. Dates sort
    chronologically and all-numeric columns numerically; anything else sorts
    as case-insensitive text."""
    values = df[column].tolist()
    present = [v for v in values if not _is_blank(v)]

    def _num(v: Any) -> float | None:
        try:
            return float(str(v).strip().replace(",", ""))
        except ValueError:
            return None

    if looks_like_date(df[column]):
        kind, key = "date", _parse_date
    elif present and all(_num(v) is not None for v in present):
        kind, key = "numeric", _num
    else:
        kind, key = "text", lambda v: str(v).strip().casefold()

    keyed = [(pos, None if _is_blank(v) else key(v)) for pos, v in enumerate(values)]
    filled = [(pos, k) for pos, k in keyed if k is not None]
    blanks = [pos for pos, k in keyed if k is None]
    # Python's sort stays stable with reverse=True, so ties keep file order.
    filled.sort(key=lambda item: item[1], reverse=(direction == "desc"))
    order = [pos for pos, _ in filled] + blanks
    return df.iloc[order].reset_index(drop=True), kind


def _combined_filename(filenames: list[str], kind: str) -> str:
    stems = "_".join(re.sub(r"[^\w\-]+", "_", PurePath(n).stem).strip("_") for n in filenames)
    stems = stems[:80].rstrip("_") or "files"
    return f"combined_{stems}.{'csv' if kind == 'csv' else 'xlsx'}"


def join_files(
    files: list[tuple[str, bytes]],
    sheets: list[str | None],
    steps: list[JoinStep],
    sort: JoinSort | None = None,
    preview_rows: int = 10,
) -> JoinResult:
    filenames = [name for name, _ in files]
    kind = validate_files(filenames)
    if len(steps) != len(files) - 1:
        raise JoinConfigError(f"Expected {len(files) - 1} join step(s), got {len(steps)}.")
    sheets = list(sheets) + [None] * (len(files) - len(sheets))

    frames: list[pd.DataFrame] = []
    for (name, content), sheet in zip(files, sheets):
        try:
            loaded = load_tabular_detailed(content, name, sheet_name=sheet or None)
        except ValueError as exc:
            raise JoinConfigError(f"{name}: {exc}") from exc
        frames.append(loaded["df"])

    for i, step in enumerate(steps):
        right_idx = i + 1
        if step.how not in JOIN_TYPES:
            raise JoinConfigError(f"Join {i + 1}: unknown join type {step.how!r}.")
        if not 0 <= step.left_file < right_idx:
            raise JoinConfigError(f"Join {i + 1}: the left key must come from a file already joined (1–{right_idx}).")
        if step.left_column not in frames[step.left_file].columns:
            raise JoinConfigError(f"Join {i + 1}: column {step.left_column!r} is not in {filenames[step.left_file]}.")
        if step.right_column not in frames[right_idx].columns:
            raise JoinConfigError(f"Join {i + 1}: column {step.right_column!r} is not in {filenames[right_idx]}.")

    renames = _collision_renames(frames, steps)
    renamed_columns = [
        {"file": idx, "filename": filenames[idx], "from": old, "to": new}
        for idx, mapping in enumerate(renames)
        for old, new in mapping.items()
    ]
    frames = [frame.rename(columns=mapping) for frame, mapping in zip(frames, renames)]

    # (file index, original column) → name in the combined frame. A right-hand
    # key column is re-pointed at its step's output key once it is merged away,
    # so a later step may still name it as its left key.
    colmap: dict[tuple[int, str], str] = {}
    for idx, frame in enumerate(frames):
        inverse = {new: old for old, new in renames[idx].items()}
        for col in frame.columns:
            colmap[(idx, inverse.get(col, col))] = col

    combined = frames[0].copy()
    step_reports: list[dict[str, Any]] = []
    missing_groups: list[dict[str, Any]] = []
    output_keys: list[str] = []

    for i, step in enumerate(steps):
        right_idx = i + 1
        left_col = colmap[(step.left_file, step.left_column)]
        right = frames[right_idx].copy()
        right_col = step.right_column
        left_label = f"File {step.left_file + 1} · {step.left_column}"
        right_label = f"File {right_idx + 1} · {right_col}"

        as_date = looks_like_date(combined[left_col]) and looks_like_date(right[right_col])

        left_missing = _missing_mask(combined[left_col])
        right_missing = _missing_mask(right[right_col])
        # Blank keys never match anything. Sides whose unmatched rows the join
        # type keeps (left for left/outer, right for outer) keep them in the
        # result as unmatched; otherwise they are excluded. Either way they are
        # reported so the user sees them.
        keep_left = step.how in ("left", "outer")
        keep_right = step.how == "outer"
        for side, frame, mask, label, kept in (
            ("left", combined, left_missing, f"Files 1–{right_idx}" if right_idx > 1 else "File 1", keep_left),
            ("right", right, right_missing, f"File {right_idx + 1}", keep_right),
        ):
            if mask.any():
                blank = frame[mask]
                missing_groups.append({
                    "step": i,
                    "side": side,
                    "label": label,
                    "key_column": left_col if side == "left" else right_col,
                    "count": int(mask.sum()),
                    "kept": kept,
                    "columns": [str(c) for c in blank.columns],
                    "preview": _row_preview(blank, preview_rows),
                })

        left = combined.copy()
        left[_LO] = range(len(left))
        left[_KEY] = [
            f"￿blank-left-{pos}" if missing else _normalize_key(v, as_date)
            for pos, (v, missing) in enumerate(zip(left[left_col], left_missing))
        ]
        right[_RO] = range(len(right))
        right[_KEY] = [
            f"￿blank-right-{pos}" if missing else _normalize_key(v, as_date)
            for pos, (v, missing) in enumerate(zip(right[right_col], right_missing))
        ]
        if not keep_left:
            left = left[~left_missing.values]
        if not keep_right:
            right = right[~right_missing.values]

        left_dups = int(left[_KEY].duplicated(keep=False).sum())
        right_dups = int(right[_KEY].duplicated(keep=False).sum())

        right_payload = right.drop(columns=[right_col])
        merged = left.merge(right_payload, on=_KEY, how=step.how, indicator=_MERGE, sort=False)
        merged = merged.sort_values([_LO, _RO], na_position="last", kind="mergesort")

        # Right-only rows (outer join) carry their key in the right column only.
        right_only = merged[_MERGE] == "right_only"
        if right_only.any():
            right_keys = right.set_index(_RO)[right_col]
            merged.loc[right_only, left_col] = merged.loc[right_only, _RO].map(right_keys).values

        matched_left_rows = int(merged.loc[merged[_MERGE] == "both", _LO].nunique())
        matched_right_rows = int(merged.loc[merged[_MERGE] == "both", _RO].nunique())
        # Rows are multiplied only when a left row appears more than once. A
        # right row reused by several left rows is an ordinary lookup.
        extra_rows = int(merged[_LO].dropna().duplicated().sum())

        step_reports.append({
            "step": i,
            "left_label": left_label,
            "right_label": right_label,
            "right_filename": filenames[right_idx],
            "output_key": left_col,
            "how": step.how,
            "matched_as_dates": as_date,
            "left_rows": int(len(combined)),
            "right_rows": int(len(frames[right_idx])),
            "left_missing_key": int(left_missing.sum()),
            "right_missing_key": int(right_missing.sum()),
            "matched_left_rows": matched_left_rows,
            "matched_right_rows": matched_right_rows,
            "left_unmatched": int(len(combined) - left_missing.sum() - matched_left_rows),
            "right_unmatched": int(len(frames[right_idx]) - right_missing.sum() - matched_right_rows),
            "left_unmatched_kept": step.how in ("left", "outer"),
            "right_unmatched_kept": step.how == "outer",
            "left_duplicate_key_rows": left_dups,
            "right_duplicate_key_rows": right_dups,
            "relationship": _relationship(left_dups, right_dups),
            "extra_rows_from_duplicates": extra_rows,
            "result_rows": int(len(merged)),
        })

        combined = merged.drop(columns=[_LO, _RO, _KEY, _MERGE]).reset_index(drop=True)
        colmap[(right_idx, right_col)] = left_col
        output_keys.append(left_col)

    sort_report = None
    if sort is not None:
        if not 0 <= sort.step < len(steps) or sort.direction not in ("asc", "desc"):
            raise JoinConfigError("Invalid sort selection.")
        sort_col = output_keys[sort.step]
        combined, sort_kind = _sort_frame(combined, sort_col, sort.direction)
        sort_report = {"column": sort_col, "direction": sort.direction, "kind": sort_kind}

    return JoinResult(
        df=combined,
        kind=kind,
        filename=_combined_filename(filenames, kind),
        steps=step_reports,
        missing_key_groups=missing_groups,
        renamed_columns=renamed_columns,
        sort=sort_report,
    )


def to_bytes(result: JoinResult) -> tuple[bytes, str]:
    """Serialise the combined frame in the same family as its inputs, so the
    downstream loader reads it exactly like a single uploaded file."""
    if result.kind == "csv":
        return result.df.to_csv(index=False).encode("utf-8"), "text/csv"
    buf = BytesIO()
    result.df.to_excel(buf, index=False, sheet_name="Combined")
    return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def summary(result: JoinResult, preview_rows: int = 10) -> dict[str, Any]:
    return {
        "filename": result.filename,
        "rows": int(len(result.df)),
        "cols": int(result.df.shape[1]),
        "columns": [str(c) for c in result.df.columns],
        "preview": _row_preview(result.df, preview_rows),
        "steps": result.steps,
        "missing_key_groups": result.missing_key_groups,
        "renamed_columns": result.renamed_columns,
        "sort": result.sort,
    }
