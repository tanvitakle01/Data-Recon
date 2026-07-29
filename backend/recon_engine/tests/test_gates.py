from __future__ import annotations

import pandas as pd

from backend.recon_engine.models.contract import DraftContract
from backend.recon_engine.validation import replay_sample, validate_structural


def _valid_draft() -> DraftContract:
    return DraftContract(
        comparison_type="sales_history",
        source_type="s4",
        target_type="ibp",
        operations=[
            {"op": "trim_string", "field": "id"},
            {"op": "numeric_cast", "field": "qty"},
        ],
        business_key=[{"source_field": "id", "target_field": "id"}],
        compare_fields=[{"source_field": "qty", "target_field": "qty"}],
        source_schema=["id", "qty"],
        target_schema=["id", "qty"],
    )


SRC_COLS = ["id", "qty"]
TGT_COLS = ["id", "qty"]


# ── Gate 1 ─────────────────────────────────────────────────────────────────

def test_gate1_accepts_valid_contract():
    report = validate_structural(_valid_draft(), SRC_COLS, TGT_COLS)
    assert report.ok, report.errors


def test_gate1_rejects_unknown_operation():
    draft = _valid_draft().model_dump()
    draft["operations"].append({"op": "run_python", "field": "id", "params": {}})
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert not report.ok
    assert any("allow-listed" in e for e in report.errors)


def test_gate1_rejects_unknown_field():
    draft = _valid_draft().model_dump()
    draft["business_key"] = [{"source_field": "ghost", "target_field": "id"}]
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert not report.ok
    assert any("ghost" in e for e in report.errors)


def test_gate1_rejects_missing_business_key():
    draft = _valid_draft().model_dump()
    draft["business_key"] = []
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert not report.ok


def test_gate1_rejects_bad_params():
    draft = _valid_draft().model_dump()
    draft["operations"] = [{"op": "date_parse", "field": "id", "params": {}}]
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert not report.ok
    assert any("source_format" in e for e in report.errors)


def test_gate1_accepts_valid_aggregate_group():
    draft = _valid_draft().model_dump()
    draft["operations"] = [
        {
            "op": "aggregate_group",
            "params": {"by": ["id"], "aggregations": [{"field": "qty", "func": "sum"}]},
        }
    ]
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert report.ok, report.errors


def test_gate1_rejects_aggregate_group_unknown_func():
    draft = _valid_draft().model_dump()
    draft["operations"] = [
        {
            "op": "aggregate_group",
            "params": {"by": ["id"], "aggregations": [{"field": "qty", "func": "bogus"}]},
        }
    ]
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert not report.ok
    assert any("unknown func" in e for e in report.errors)


def test_gate1_rejects_aggregate_group_unknown_field():
    draft = _valid_draft().model_dump()
    draft["operations"] = [
        {
            "op": "aggregate_group",
            "params": {"by": ["ghost"], "aggregations": [{"field": "qty", "func": "sum"}]},
        }
    ]
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert not report.ok
    assert any("ghost" in e for e in report.errors)


def test_gate1_tracks_rename_for_later_ops():
    draft = _valid_draft().model_dump()
    draft["operations"] = [
        {"op": "rename_field", "field": "id", "params": {"to": "ident"}},
        {"op": "trim_string", "field": "ident", "params": {}},
    ]
    draft["business_key"] = [{"source_field": "ident", "target_field": "id"}]
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert report.ok, report.errors


def test_gate1_accepts_value_transformation_ops():
    """The objective's Plant example: prefix then suffix, plus a Material
    substring replace — all executable operations, all valid at Gate 1."""
    draft = _valid_draft().model_dump()
    draft["operations"] = [
        {"op": "prepend_prefix", "field": "id", "params": {"value": "PL"}},
        {"op": "append_suffix", "field": "id", "params": {"value": "@S21400"}},
        {"op": "replace_value", "field": "id", "params": {"from": "N01", "to": "T01"}},
    ]
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert report.ok, report.errors


def test_gate1_rejects_value_op_missing_required_param():
    draft = _valid_draft().model_dump()
    draft["operations"] = [{"op": "prepend_prefix", "field": "id", "params": {}}]
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert not report.ok
    assert any("value" in e for e in report.errors)


def test_gate1_rejects_business_key_that_does_not_survive_transformation():
    """Rule #3: a business key renamed away no longer exists in the shadow —
    Gate 1 must catch that rather than let reconciliation blow up."""
    draft = _valid_draft().model_dump()
    draft["operations"] = [{"op": "rename_field", "field": "id", "params": {"to": "gone"}}]
    # business_key still references the original "id", which no longer exists.
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert not report.ok
    assert any("survive transformation" in e or "does not exist after" in e for e in report.errors)


def test_gate1_tracks_concat_fields_new_column():
    draft = _valid_draft().model_dump()
    draft["operations"] = [
        {"op": "concat_fields", "params": {"fields": ["id", "qty"], "into": "composite", "separator": "-"}},
    ]
    draft["business_key"] = [{"source_field": "composite", "target_field": "id"}]
    report = validate_structural(draft, SRC_COLS, TGT_COLS)
    assert report.ok, report.errors


# ── Gate 2 ─────────────────────────────────────────────────────────────────

def _sample(n: int = 60) -> pd.DataFrame:
    return pd.DataFrame({"id": [f"K{i}" for i in range(n)], "qty": list(range(n))})


def test_gate2_passes_on_clean_sample():
    src = _sample()
    tgt = _sample()
    report = replay_sample(_valid_draft(), src, tgt)
    assert report.ok, report.errors


def test_gate2_flags_bad_date_parse():
    draft = _valid_draft().model_dump()
    draft["operations"] = [{"op": "date_parse", "field": "id", "params": {"source_format": "DD.MM.YYYY"}}]
    # "K0".. are not dates -> parse rate 0 -> failure.
    report = replay_sample(draft, _sample(), _sample())
    assert not report.ok
    assert any("date_parse" in e for e in report.errors)
