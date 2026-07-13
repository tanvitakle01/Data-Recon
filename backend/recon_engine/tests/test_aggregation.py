"""Aggregation rules: executor staging, the Filters→Transforms→Aggregations
order, gate validation, and compile pass-through.
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine import service
from backend.recon_engine.compiler import StubContractCompiler
from backend.recon_engine.engine import LINEAGE_COL, build_shadow_source
from backend.recon_engine.models.contract import DraftContract, TransformationContract
from backend.recon_engine.models.snapshot import RawLayer
from backend.recon_engine.validation import validate_structural


def _contract(**over) -> TransformationContract:
    base = dict(
        contract_id="c1",
        contract_version=1,
        comparison_type="sales_history",
        source_type="s4",
        target_type="ibp",
        operations=[],
        business_key=[{"source_field": "Plant", "target_field": "LOCID"}],
        compare_fields=[{"source_field": "Qty", "target_field": "QTY"}],
        source_schema=["Plant", "Qty"],
        target_schema=["LOCID", "QTY"],
    )
    base.update(over)
    return TransformationContract(**base)


def _draft_dict(**over) -> dict:
    """A Gate-1-shaped draft dict (no provenance fields, which DraftContract forbids)."""
    base = dict(
        comparison_type="sales_history",
        source_type="s4",
        target_type="ibp",
        operations=[],
        business_key=[{"source_field": "Plant", "target_field": "LOCID"}],
        compare_fields=[{"source_field": "Qty", "target_field": "QTY"}],
        source_schema=["Plant", "Qty"],
        target_schema=["LOCID", "QTY"],
    )
    base.update(over)
    return DraftContract(**base).model_dump()


# ── executor: measure aggregation ────────────────────────────────────────────

def test_sum_aggregation_groups_by_business_key():
    contract = _contract(aggregation_rules=[{"source_field": "Qty", "aggregation": "sum"}])
    raw = pd.DataFrame({"Plant": ["A", "A", "B"], "Qty": [10, 15, 7]})
    built = build_shadow_source(contract, raw)
    result = dict(zip(built.shadow_df["Plant"], built.shadow_df["Qty"]))
    assert result == {"A": 25, "B": 7}
    # Lineage collapses to the group.
    lineage = {p: q for p, q in zip(built.shadow_df["Plant"], built.lineage)}
    assert sorted(lineage["A"]) == [0, 1]


def test_group_by_month_buckets_date_then_groups():
    contract = _contract(
        business_key=[
            {"source_field": "Plant", "target_field": "LOCID"},
            {"source_field": "Date", "target_field": "KEYFIGUREDATE"},
        ],
        aggregation_rules=[
            {"source_field": "Date", "aggregation": "group_by_month"},
            {"source_field": "Qty", "aggregation": "sum"},
        ],
        source_schema=["Plant", "Date", "Qty"],
        target_schema=["LOCID", "KEYFIGUREDATE", "QTY"],
    )
    raw = pd.DataFrame({
        "Plant": ["A", "A", "A"],
        "Date": ["2025-08-05", "2025-08-19", "2025-09-02"],
        "Qty": [10, 5, 3],
    })
    built = build_shadow_source(contract, raw)
    got = {(r["Plant"], r["Date"]): r["Qty"] for _, r in built.shadow_df.iterrows()}
    # Aug rows collapse to 2025-08-01 (period start) summing 15; Sep separate.
    assert got == {("A", "2025-08-01"): 15, ("A", "2025-09-01"): 3}


def test_min_max_count_average():
    for agg, expected in [("min", 5), ("max", 20), ("count", 3), ("average", 11)]:
        contract = _contract(aggregation_rules=[{"source_field": "Qty", "aggregation": agg}])
        raw = pd.DataFrame({"Plant": ["A", "A", "A"], "Qty": [5, 8, 20]})
        built = build_shadow_source(contract, raw)
        assert built.shadow_df["Qty"].iloc[0] == expected, agg


# ── executor: pipeline ordering ──────────────────────────────────────────────

def test_pipeline_order_filter_then_transform_then_aggregate():
    """Filter MaterialGroup=FG (raw) → transform Plant → sum Qty by Plant. The
    incidental MaterialGroup column is dropped by the aggregation (it is neither
    a group key nor a measure/compare field), leaving only reconciled fields."""
    contract = _contract(
        operations=[
            # Deliberately listed transform-before-filter to prove the engine
            # re-orders to Filters → Transformations regardless of list order.
            {"op": "prepend_prefix", "field": "Plant", "params": {"value": "PL"}},
            {"op": "include_value", "field": "MaterialGroup", "params": {"values": ["FG"]}},
        ],
        aggregation_rules=[{"source_field": "Qty", "aggregation": "sum"}],
        source_schema=["Plant", "MaterialGroup", "Qty"],
        target_schema=["LOCID", "QTY"],
    )
    raw = pd.DataFrame({
        "Plant": ["5006", "5006", "5007"],
        "MaterialGroup": ["FG", "RAW", "FG"],
        "Qty": [10, 99, 4],
    })
    built = build_shadow_source(contract, raw)
    # RAW row filtered out; Plant prefixed; Qty summed per Plant.
    result = {r["Plant"]: r["Qty"] for _, r in built.shadow_df.iterrows()}
    assert result == {"PL5006": 10, "PL5007": 4}
    # Incidental column dropped by aggregation; only reconciled fields (+ lineage) remain.
    assert "MaterialGroup" not in built.shadow_df.columns
    assert set(built.shadow_df.columns) == {"Plant", "Qty", LINEAGE_COL}


# ── Gate 1 ────────────────────────────────────────────────────────────────────

def test_gate1_accepts_valid_aggregation():
    draft = _draft_dict(
        aggregation_rules=[{"source_field": "Qty", "aggregation": "sum"}],
        source_schema=["Plant", "Qty"],
    )
    report = validate_structural(draft, ["Plant", "Qty"], ["LOCID", "QTY"])
    assert report.ok, report.errors


def test_gate1_rejects_aggregation_on_missing_field():
    draft = _draft_dict(aggregation_rules=[{"source_field": "Ghost", "aggregation": "sum"}])
    report = validate_structural(draft, ["Plant", "Qty"], ["LOCID", "QTY"])
    assert not report.ok
    assert any("Ghost" in e for e in report.errors)


# ── compile pass-through ──────────────────────────────────────────────────────

def test_compile_draft_attaches_resolved_aggregation():
    draft, _ = service.compile_draft(
        mapping_sheet=[
            {"source_col": "Plant", "target_col": "LOCID", "role": "key"},
            {"source_col": "ReqDlvQty", "target_col": "SALESORDERREQUEST", "role": "compare"},
        ],
        rules="",
        aggregation_rules=[
            {"source_field": "reqdlvqty", "aggregation": "sum"},  # lower-case -> resolved
        ],
        source_schema=["Plant", "ReqDlvQty", "MaterialGroup"],
        target_schema=["LOCID", "SALESORDERREQUEST"],
        comparison_type="custom", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )
    assert [(a.source_field, a.aggregation.value) for a in draft.aggregation_rules] == [
        ("ReqDlvQty", "sum")
    ]


# ── end-to-end through the service ────────────────────────────────────────────

def test_full_pipeline_aggregates_and_reconciles():
    source_df = pd.DataFrame({
        "Plant": ["5006", "5006", "5006"],
        "Material": ["N01-FG01", "N01-FG01", "N01-FG01"],
        "MaterialGroup": ["FG", "FG", "RAW"],
        "Date": ["2025-08-05", "2025-08-19", "2025-08-10"],
        "Qty": [10, 5, 999],
    })
    # Target: one monthly bucket for the FG rows summing to 15.
    target_df = pd.DataFrame({
        "LOCID": ["5006"], "PRDID": ["N01-FG01"], "KEYFIGUREDATE": ["2025-08-01"], "QTY": [15],
    })
    src = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")

    # Contract: filter MaterialGroup=FG, group by month, sum Qty.
    draft = DraftContract(
        comparison_type="custom", source_type="excel", target_type="excel",
        operations=[{"op": "include_value", "field": "MaterialGroup", "params": {"values": ["FG"]}}],
        aggregation_rules=[
            {"source_field": "Date", "aggregation": "group_by_month"},
            {"source_field": "Qty", "aggregation": "sum"},
        ],
        business_key=[
            {"source_field": "Plant", "target_field": "LOCID"},
            {"source_field": "Material", "target_field": "PRDID"},
            {"source_field": "Date", "target_field": "KEYFIGUREDATE"},
        ],
        compare_fields=[{"source_field": "Qty", "target_field": "QTY"}],
        source_schema=list(source_df.columns),
        target_schema=list(target_df.columns),
    )
    contract = service.approve_contract(draft, approved_by="alice")
    out = service.run_reconciliation(
        contract_id=contract.contract_id,
        source_snapshot_id=src.snapshot_id,
        target_snapshot_id=tgt.snapshot_id,
    )
    # The two FG August rows aggregate to Qty 15 in the 2025-08-01 bucket and match.
    assert out["summary"]["match"] == 1, out["summary"]
    assert out["summary"].get("mismatch", 0) == 0
