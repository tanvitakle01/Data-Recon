"""Coverage for engine.anchor_inference.infer_anchor_date — recovering a
run's date anchor from a frozen target extract by inverting the approved
contract's own relative_date_reassign rule, never a hardcoded date/weekday."""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.engine.anchor_inference import infer_anchor_date
from backend.recon_engine.models.contract import (
    BusinessKeyField,
    ContractOperation,
    TransformationContract,
)


def _contract(operations, business_key=None, compare_fields=None):
    return TransformationContract(
        contract_id="c1", contract_version=1,
        comparison_type="custom", source_type="excel", target_type="excel",
        operations=[ContractOperation(**op) for op in operations],
        business_key=[BusinessKeyField(**k) for k in (business_key or [])],
        compare_fields=compare_fields or [],
        approved_by="alice",
    )


def _reassign_op(offset_days: int, weekday_exception: dict | None = None, field: str = "KEYFIGUREDATE"):
    params = {"date_condition": "lt", "offset_days": offset_days}
    if weekday_exception is not None:
        params["weekday_exception"] = weekday_exception
    return {"op": "relative_date_reassign", "field": field, "params": params}


def test_infers_anchor_with_no_weekday_exception():
    contract = _contract([_reassign_op(offset_days=1)])
    target = pd.DataFrame({"KEYFIGUREDATE": ["2026-01-02"]})
    result = infer_anchor_date(contract, target)
    assert result.anchor_date == "2026-01-01"
    assert result.support == 1
    assert result.total == 1
    assert result.confidence == 1.0


def test_infers_anchor_respecting_weekday_exception():
    """2026-09-04 is a Friday: offset_days=1 with a Saturday exception of +2
    must invert to 2026-09-03 (a Thursday, so the base branch — not the
    exception — applies), matching what the operation itself would have
    produced running forward."""
    contract = _contract([
        _reassign_op(offset_days=1, weekday_exception={"on_weekday": "Saturday", "offset_days": 2}),
    ])
    target = pd.DataFrame({"KEYFIGUREDATE": ["9/4/2026"] * 5})
    result = infer_anchor_date(contract, target)
    assert result.anchor_date == "2026-09-03"
    assert result.support == 5
    assert result.total == 5


def test_tied_candidates_yield_exactly_half_confidence_not_a_silent_guess():
    """A single repeated target date can be genuinely ambiguous between two
    self-consistent explanations: "anchor was the Saturday two days ago (the
    exception fired)" and "anchor was the very next day, a Sunday (the base
    offset applied)" — both invert to the SAME output date when the
    exception/base offsets differ by exactly 1. Neither can be preferred from
    this single value alone; the caller (``service._resolve_run_anchor``)
    treats an exact tie as not confident enough to act on, rather than
    silently picking one — see ``test_run_date_anchor.
    test_tied_anchor_inference_falls_back_to_wall_clock``."""
    contract = _contract([
        _reassign_op(offset_days=1, weekday_exception={"on_weekday": "Saturday", "offset_days": 2}),
    ])
    # 2026-01-05 is a Monday: exception-branch anchor = 2026-01-03 (Saturday,
    # self-consistent); base-branch anchor = 2026-01-04 (Sunday, also
    # self-consistent) — a genuine structural tie, not a bug.
    target = pd.DataFrame({"KEYFIGUREDATE": ["2026-01-05"]})
    result = infer_anchor_date(contract, target)
    assert result.confidence == 0.5
    assert result.total == 2


def test_uses_business_key_mapping_to_find_the_target_column():
    """The operation's ``field`` names the SOURCE column; the target-side
    counterpart can be named differently and must be resolved via the
    human-confirmed business_key mapping, never assumed to share a name."""
    contract = _contract(
        [_reassign_op(offset_days=1, field="KEYFIGUREDATE")],
        business_key=[{"source_field": "KEYFIGUREDATE", "target_field": "TARGET_DATE"}],
    )
    target = pd.DataFrame({"TARGET_DATE": ["2026-01-02"]})
    result = infer_anchor_date(contract, target)
    assert result.field == "TARGET_DATE"
    assert result.anchor_date == "2026-01-01"


def test_majority_wins_when_target_dates_disagree():
    contract = _contract([_reassign_op(offset_days=1)])
    target = pd.DataFrame({"KEYFIGUREDATE": ["2026-01-02"] * 8 + ["2026-03-15"] * 2})
    result = infer_anchor_date(contract, target)
    assert result.anchor_date == "2026-01-01"
    assert result.support == 8
    assert result.total == 10
    assert result.confidence == 0.8


def test_no_relative_date_reassign_operation_yields_no_inference():
    contract = _contract([{"op": "date_window_filter", "field": "KEYFIGUREDATE", "params": {}}])
    target = pd.DataFrame({"KEYFIGUREDATE": ["2026-01-02"]})
    result = infer_anchor_date(contract, target)
    assert result.anchor_date is None
    assert result.reason is not None


def test_reassign_compared_to_another_column_yields_no_inference():
    """A rule compared against a COLUMN (not run_date) has no run-time
    anchor to invert at all."""
    op = _reassign_op(offset_days=1)
    op["params"]["compare_to"] = "OTHER_DATE"
    contract = _contract([op])
    target = pd.DataFrame({"KEYFIGUREDATE": ["2026-01-02"], "OTHER_DATE": ["2025-01-01"]})
    result = infer_anchor_date(contract, target)
    assert result.anchor_date is None


def test_missing_target_column_yields_no_inference():
    contract = _contract([_reassign_op(offset_days=1, field="KEYFIGUREDATE")])
    target = pd.DataFrame({"SOMETHING_ELSE": ["2026-01-02"]})
    result = infer_anchor_date(contract, target)
    assert result.anchor_date is None
    assert result.reason is not None


def test_unparseable_target_dates_yield_no_inference():
    contract = _contract([_reassign_op(offset_days=1)])
    target = pd.DataFrame({"KEYFIGUREDATE": ["not-a-date", "also-not-a-date"]})
    result = infer_anchor_date(contract, target)
    assert result.anchor_date is None
