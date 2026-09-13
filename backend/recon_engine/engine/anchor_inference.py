"""Infer a run's date anchor from a FROZEN target extract, instead of
requiring a human to work it out by hand.

Background (the "5CIR ECC->IBP" case this generalizes from): a
``relative_date_reassign`` "roll a past-due date forward" rule is anchored to
wall-clock "now" by default — correct for a live run where source and target
are both freshly pulled today, but a static target extract captured on an
EARLIER day can only ever match the rule when it is replayed anchored to that
same earlier day (see ``service.run_reconciliation``'s ``anchor_date``
param). Nothing about *which* day that was is available anywhere except the
target data itself: the target extract's own date-bearing column already
carries the rule's OUTPUT for whatever anchor produced it, so that anchor can
be recovered by inverting the rule against it.

Deterministic and value-based ONLY, matching the rest of this package
(``date_detection``, ``key_normalization``): no LLM, no column-name guess, no
hardcoded calendar date or weekday — every number and name used below comes
from the APPROVED CONTRACT'S OWN ``relative_date_reassign`` operation
(``offset_days``, ``weekday_exception``) and the TARGET'S OWN sampled values.
A dataset with a different offset, a different (or no) weekday exception, or
no such rule at all is handled the same way, with no code change.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.recon_engine.date_detection import parse_date_series
from backend.recon_engine.operations.ops import resolve_weekday


@dataclass(frozen=True)
class AnchorInference:
    """Result of :func:`infer_anchor_date`.

    ``anchor_date`` is ``None`` when nothing could be inferred (no eligible
    operation, no matching/parseable target column, or no weekday-consistent
    candidate — see ``reason``); callers must fall back to another resolver
    (explicit override, or wall-clock) rather than treat ``None`` as "today".

    ``support``/``total`` describe how much of the target's own data backs
    the winning candidate (e.g. 56/56 rows imply the same anchor) — surfaced
    for audit rather than silently trusted, the same posture
    ``DateFormatSpec.ambiguous`` takes for date-format detection.
    """

    anchor_date: str | None
    field: str | None
    support: int
    total: int
    reason: str | None

    @property
    def confidence(self) -> float | None:
        return (self.support / self.total) if self.total else None


def _target_field_for(contract: Any, source_field: str) -> str:
    """The target-side column a contract operation's source ``field`` name
    corresponds to, via the human-confirmed business_key/compare_fields
    mapping — never guessed. Falls back to the SAME name when the field
    isn't part of either mapping (e.g. source and target already share a
    column name, as a pre-mapped extract commonly does)."""
    for k in contract.business_key:
        if k.source_field == source_field:
            return k.target_field
    for c in contract.compare_fields:
        if c.source_field == source_field:
            return c.target_field
    return source_field


def _reassign_op_anchored_to_run_date(contract: Any) -> Any | None:
    """The first enabled ``relative_date_reassign`` operation compared
    against ``run_date`` (the default ``compare_to``) — the only kind an
    anchor can be recovered from; a rule compared against another COLUMN has
    no run-time anchor to invert."""
    for op in contract.operations:
        if op.op != "relative_date_reassign" or not op.enabled:
            continue
        if str(op.params.get("compare_to") or "run_date") == "run_date":
            return op
    return None


def infer_anchor_date(contract: Any, target_df: pd.DataFrame) -> AnchorInference:
    """Recover the run_date that produced ``target_df``'s own date-bearing
    column, by inverting the approved contract's ``relative_date_reassign``
    rule against it.

    For each distinct value in the target's column (weighted by how many
    rows carry it), tries both of the rule's possible branches:
      * the base ``offset_days`` — valid only if the implied anchor's weekday
        is NOT the rule's ``weekday_exception`` weekday (otherwise the
        exception branch would have fired instead, producing a different
        date);
      * the exception's own ``offset_days`` — valid only if the implied
        anchor's weekday IS that weekday.
    Every value contributes its row count to whichever branch(es) are
    weekday-consistent for it; the anchor with the most total support wins.
    This naturally covers both a single-day extract (one distinct value,
    trivially "wins") and a multi-day batch load, without special-casing
    either.
    """
    op = _reassign_op_anchored_to_run_date(contract)
    if op is None:
        return AnchorInference(
            anchor_date=None, field=None, support=0, total=0,
            reason="Contract has no relative_date_reassign operation anchored to run_date.",
        )

    field = _target_field_for(contract, op.field)
    if field not in target_df.columns:
        return AnchorInference(
            anchor_date=None, field=field, support=0, total=0,
            reason=f"Target has no column '{field}' to read the rule's own output from.",
        )

    parsed = parse_date_series(target_df[field])
    if parsed.notna().sum() == 0:
        return AnchorInference(
            anchor_date=None, field=field, support=0, total=0,
            reason=f"Target column '{field}' has no parseable dates.",
        )

    offset_days = int(op.params["offset_days"])
    weekday_exception = op.params.get("weekday_exception")
    exception_weekday = resolve_weekday(weekday_exception["on_weekday"]) if weekday_exception else None
    exception_offset = int(weekday_exception["offset_days"]) if weekday_exception else None

    value_counts = parsed.dropna().dt.normalize().value_counts()
    candidates: Counter[pd.Timestamp] = Counter()
    for value, count in value_counts.items():
        base_anchor = value - pd.Timedelta(days=offset_days)
        if exception_weekday is None or base_anchor.weekday() != exception_weekday:
            candidates[base_anchor] += int(count)
        if exception_weekday is not None:
            exception_anchor = value - pd.Timedelta(days=exception_offset)
            if exception_anchor.weekday() == exception_weekday:
                candidates[exception_anchor] += int(count)

    if not candidates:
        return AnchorInference(
            anchor_date=None, field=field, support=0, total=0,
            reason=(
                f"No weekday-consistent anchor reproduces '{field}'s values under this "
                "contract's relative_date_reassign rule."
            ),
        )

    best_anchor, support = candidates.most_common(1)[0]
    total = sum(candidates.values())
    return AnchorInference(
        anchor_date=best_anchor.date().isoformat(), field=field,
        support=support, total=total, reason=None,
    )
