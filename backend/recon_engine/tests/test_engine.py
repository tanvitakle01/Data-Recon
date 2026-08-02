from __future__ import annotations

import json

import pandas as pd

from backend.recon_engine.engine import LINEAGE_COL, build_shadow_source, reconcile
from backend.recon_engine.models.contract import DraftContract, TransformationContract
from backend.recon_engine.models.value_mapping import Confidence, ValueMapping, ValueMatch


def _contract(**over) -> TransformationContract:
    base = dict(
        contract_id="c1",
        contract_version=1,
        comparison_type="sales_history",
        source_type="s4",
        target_type="ibp",
        operations=[{"op": "trim_string", "field": "id"}, {"op": "numeric_cast", "field": "qty"}],
        business_key=[{"source_field": "id", "target_field": "id"}],
        compare_fields=[{"source_field": "qty", "target_field": "qty"}],
        source_schema=["id", "qty"],
        target_schema=["id", "qty"],
    )
    base.update(over)
    return TransformationContract(**base)


def test_executor_transforms_and_records_lineage():
    contract = _contract()
    raw = pd.DataFrame({"id": ["  a ", " b"], "qty": ["1", "2"]})
    built = build_shadow_source(contract, raw)
    assert built.shadow_df["id"].tolist() == ["a", "b"]
    assert built.shadow_df["qty"].tolist() == [1.0, 2.0]
    assert built.lineage == [[0], [1]]
    assert LINEAGE_COL in built.shadow_df.columns


def test_executor_never_mutates_raw():
    contract = _contract()
    raw = pd.DataFrame({"id": ["  a "], "qty": ["1"]})
    _ = build_shadow_source(contract, raw)
    assert raw["id"].tolist() == ["  a "]  # untouched


def test_executor_aggregate_lineage():
    contract = _contract(
        operations=[{"op": "sum_aggregate", "field": "v", "params": {"by": ["k"]}}],
        business_key=[{"source_field": "k", "target_field": "k"}],
        compare_fields=[{"source_field": "v", "target_field": "v"}],
        source_schema=["k", "v"],
        target_schema=["k", "v"],
    )
    raw = pd.DataFrame({"k": ["x", "x", "y"], "v": [1, 2, 3]})
    built = build_shadow_source(contract, raw)
    rows = dict(zip(built.shadow_df["k"], built.shadow_df["v"]))
    assert rows == {"x": 3, "y": 3}
    lineage_map = {
        k: json.loads(ids)
        for k, ids in zip(built.shadow_df["k"], built.shadow_df[LINEAGE_COL])
    }
    assert lineage_map == {"x": [0, 1], "y": [2]}


def test_executor_aggregate_group_lineage():
    # "Aggregate & Group" combined step: Group By + Sum in one op.
    contract = _contract(
        operations=[
            {
                "op": "aggregate_group",
                "params": {"by": ["k"], "aggregations": [{"field": "v", "func": "sum"}]},
            }
        ],
        business_key=[{"source_field": "k", "target_field": "k"}],
        compare_fields=[{"source_field": "v", "target_field": "v"}],
        source_schema=["k", "v"],
        target_schema=["k", "v"],
    )
    raw = pd.DataFrame({"k": ["x", "x", "y"], "v": [1, 2, 3]})
    built = build_shadow_source(contract, raw)
    rows = dict(zip(built.shadow_df["k"], built.shadow_df["v"]))
    assert rows == {"x": 3, "y": 3}
    lineage_map = {
        k: json.loads(ids)
        for k, ids in zip(built.shadow_df["k"], built.shadow_df[LINEAGE_COL])
    }
    assert lineage_map == {"x": [0, 1], "y": [2]}


def test_apply_bucket_reaches_join_hold_out_bucket_is_excluded():
    """VERY_HIGH/HIGH Material+Plant rows reach the join; MEDIUM/NONE ones are
    held out entirely rather than silently rejoining on their unresolved raw
    value — so they never get misclassified as a mismatch."""
    contract = _contract(
        operations=[],
        business_key=[
            {"source_field": "Material", "target_field": "PRDID"},
            {"source_field": "Plant", "target_field": "LOCID"},
        ],
        compare_fields=[{"source_field": "Qty", "target_field": "QTY"}],
        source_schema=["Material", "Plant", "Qty"],
        target_schema=["PRDID", "LOCID", "QTY"],
        value_mappings=[
            ValueMapping(
                source_field="Material",
                target_field="PRDID",
                matches=[
                    ValueMatch(
                        source_value="MAT-A", target_value="MAT-A",
                        confidence=Confidence.VERY_HIGH, rule="t", evidence="e",
                    ),
                    ValueMatch(
                        source_value="MAT-B", target_value=None,
                        confidence=Confidence.MEDIUM, rule="t", evidence="e",
                    ),
                ],
            ),
            ValueMapping(
                source_field="Plant",
                target_field="LOCID",
                matches=[
                    ValueMatch(
                        source_value="PL01", target_value="PL01",
                        confidence=Confidence.VERY_HIGH, rule="t", evidence="e",
                    ),
                    ValueMatch(
                        source_value="PL99", target_value=None,
                        confidence=Confidence.NONE, rule="t", evidence="e",
                    ),
                ],
            ),
        ],
    )
    raw = pd.DataFrame({
        "Material": ["MAT-A", "MAT-B", "MAT-A"],
        "Plant": ["PL01", "PL01", "PL99"],
        "Qty": [10, 20, 30],
    })
    built = build_shadow_source(contract, raw)

    # Only the fully APPLY-eligible row (MAT-A/PL01) reaches the shadow.
    assert built.shadow_df["Material"].tolist() == ["MAT-A"]
    assert built.shadow_df["Plant"].tolist() == ["PL01"]

    held_out_by_field = {(h["field"], h["source_value"]): h["row_count"] for h in built.held_out}
    assert held_out_by_field[("Material", "MAT-B")] == 1
    assert held_out_by_field[("Plant", "PL99")] == 1

    target = pd.DataFrame({"PRDID": ["MAT-A"], "LOCID": ["PL01"], "QTY": [10]})
    recon = reconcile(contract, built.shadow_df, target)
    assert recon.summary.match == 1
    assert recon.summary.mismatch == 0  # held-out rows never misclassified


def test_apply_value_mappings_expands_row_per_multi_candidate_and_reconciles_by_record():
    """A source value with TWO accepted candidates (see value_pairing.pipeline
    module docstring — no forced single winner) duplicates into two shadow
    rows, same lineage. Reconciliation's per-record date+quantity compare then
    decides which candidate is real for this row; the spurious candidate's
    duplicate simply produces no Match rather than being silently dropped."""
    contract = _contract(
        operations=[],
        business_key=[
            {"source_field": "Material", "target_field": "PRDID"},
            {"source_field": "Date", "target_field": "Date"},
        ],
        compare_fields=[{"source_field": "Qty", "target_field": "QTY"}],
        source_schema=["Material", "Date", "Qty"],
        target_schema=["PRDID", "Date", "QTY"],
        value_mappings=[
            ValueMapping(
                source_field="Material",
                target_field="PRDID",
                matches=[
                    ValueMatch(
                        source_value="7000", target_value="7000",
                        confidence=Confidence.VERY_HIGH, rule="value_pairing.identity", evidence="e",
                        candidates=["7000", "PL7000@S500"],
                    ),
                    ValueMatch(
                        source_value="7000", target_value="PL7000@S500",
                        confidence=Confidence.HIGH, rule="value_pairing.pattern_reused", evidence="e",
                        candidates=["7000", "PL7000@S500"],
                    ),
                ],
            ),
        ],
    )
    raw = pd.DataFrame({"Material": ["7000"], "Date": ["2024-01-01"], "Qty": [10]})
    built = build_shadow_source(contract, raw)

    # One raw row expands into two shadow rows, one per candidate — identical
    # lineage (both derive from the same raw row).
    assert sorted(built.shadow_df["Material"].tolist()) == ["7000", "PL7000@S500"]
    assert built.lineage == [[0], [0]]

    # Only the row whose candidate matches the REAL target key produces a
    # Match; the other candidate's row simply finds no matching target row.
    target = pd.DataFrame({"PRDID": ["PL7000@S500"], "Date": ["2024-01-01"], "QTY": [10]})
    recon = reconcile(contract, built.shadow_df, target)
    assert recon.summary.match == 1
    assert recon.summary.mismatch == 1  # the spurious "7000" candidate row


def test_build_shadow_source_is_deterministic_with_value_mappings():
    contract = _contract(
        operations=[],
        business_key=[{"source_field": "Material", "target_field": "PRDID"}],
        compare_fields=[{"source_field": "Qty", "target_field": "QTY"}],
        source_schema=["Material", "Qty"],
        target_schema=["PRDID", "QTY"],
        value_mappings=[
            ValueMapping(
                source_field="Material",
                target_field="PRDID",
                matches=[
                    ValueMatch(
                        source_value="MAT-A", target_value="MAT-A",
                        confidence=Confidence.VERY_HIGH, rule="t", evidence="e",
                    ),
                    ValueMatch(
                        source_value="MAT-B", target_value=None,
                        confidence=Confidence.MEDIUM, rule="t", evidence="e",
                    ),
                ],
            ),
        ],
    )
    raw = pd.DataFrame({"Material": ["MAT-A", "MAT-B"], "Qty": [1, 2]})
    run1 = build_shadow_source(contract, raw)
    run2 = build_shadow_source(contract, raw)
    assert run1.shadow_df.drop(columns=[LINEAGE_COL]).equals(run2.shadow_df.drop(columns=[LINEAGE_COL]))
    assert run1.held_out == run2.held_out


def test_value_mapping_sees_post_transform_values():
    """Ordering regression guard: the executor runs Filters -> Transforms ->
    Value Mapping -> Aggregations, so value-pairing resolves whatever the
    recipe's transforms produce, not the raw source value. Here the recipe
    uppercases Material BEFORE value-mapping runs; the value_mapping's own
    ValueMatch is keyed on the POST-transform value ("MAT-A"), which only
    resolves if value-mapping truly runs after the transform."""
    contract = _contract(
        operations=[{"op": "uppercase", "field": "Material"}],
        business_key=[{"source_field": "Material", "target_field": "PRDID"}],
        compare_fields=[{"source_field": "Qty", "target_field": "QTY"}],
        source_schema=["Material", "Qty"],
        target_schema=["PRDID", "QTY"],
        value_mappings=[
            ValueMapping(
                source_field="Material",
                target_field="PRDID",
                matches=[
                    ValueMatch(
                        source_value="MAT-A", target_value="MAT-A",
                        confidence=Confidence.VERY_HIGH, rule="value_pairing.identity", evidence="e",
                    ),
                ],
            ),
        ],
    )
    raw = pd.DataFrame({"Material": ["mat-a"], "Qty": [10]})
    built = build_shadow_source(contract, raw)

    # If value-mapping ran BEFORE the transform, it would look up "mat-a" (no
    # match record for it) and hold the row out entirely. Since it runs AFTER,
    # it looks up "MAT-A" (the transform's output) and matches.
    assert built.shadow_df["Material"].tolist() == ["MAT-A"]
    assert built.held_out == []


def test_reconciler_classifies_all_buckets():
    contract = _contract()
    shadow = pd.DataFrame({"id": ["A", "B", "C"], "qty": [10, 20, 30]})
    target = pd.DataFrame({"id": ["A", "B", "D"], "qty": [10, 25, 40]})
    result = reconcile(contract, shadow, target)
    s = result.summary
    assert s.match == 1  # A
    assert s.quantity_mismatch == 1  # B (20 vs 25)
    assert s.mismatch == 2  # C (missing in target) + D (extra in target)
    assert s.total == 4


def test_reconciler_tolerance_and_exception():
    contract = _contract(
        compare_fields=[
            {"source_field": "qty", "target_field": "qty", "match_type": "tolerance", "tolerance": 2}
        ]
    )
    shadow = pd.DataFrame({"id": ["A", "B"], "qty": [10, 10]})
    target = pd.DataFrame({"id": ["A", "B"], "qty": [11, 20]})
    result = reconcile(contract, shadow, target)
    assert result.summary.match == 1  # within tolerance 2
    assert result.summary.quantity_mismatch == 1  # diff 10 > tolerance


def test_match_invariant_float_representation_artifact_is_match():
    # Values that are logically equal but differ only in IEEE-754 float noise
    # (0.1 + 0.2 == 0.30000000000000004) MUST classify as Match, not Mismatch.
    contract = _contract(
        compare_fields=[{"source_field": "qty", "target_field": "qty", "match_type": "exact"}]
    )
    shadow = pd.DataFrame({"id": ["A"], "qty": [0.1 + 0.2]})
    target = pd.DataFrame({"id": ["A"], "qty": [0.3]})
    result = reconcile(contract, shadow, target)
    assert result.summary.match == 1
    assert result.summary.quantity_mismatch == 0


def test_match_invariant_identical_values_differently_typed():
    # Keys align and the compare value is numerically identical but typed /
    # formatted differently on each side (Decimal 6dp vs float) -> MUST be Match.
    from decimal import Decimal

    contract = _contract(
        compare_fields=[{"source_field": "qty", "target_field": "qty", "match_type": "exact"}]
    )
    shadow = pd.DataFrame({"id": ["A"], "qty": [Decimal("100.000000")]})
    target = pd.DataFrame({"id": ["A"], "qty": [100.0]})
    result = reconcile(contract, shadow, target)
    assert result.summary.match == 1
    assert result.summary.quantity_mismatch == 0


def test_match_invariant_genuine_delta_is_mismatch():
    # A real numeric difference must still surface as Quantity Mismatch — the
    # invariant must not swallow genuine deltas (e.g. source 100 vs target 0).
    contract = _contract(
        compare_fields=[{"source_field": "qty", "target_field": "qty", "match_type": "exact"}]
    )
    shadow = pd.DataFrame({"id": ["A"], "qty": [100.0]})
    target = pd.DataFrame({"id": ["A"], "qty": [0.0]})
    result = reconcile(contract, shadow, target)
    assert result.summary.quantity_mismatch == 1
    assert result.summary.match == 0


def test_reconciler_deduplicates_key():
    # Duplicate business keys are deduplicated per side (keep first). The single
    # surviving key reconciles normally — no exception path exists.
    contract = _contract(compare_fields=[])
    shadow = pd.DataFrame({"id": ["A", "A"], "qty": [1, 1]})
    target = pd.DataFrame({"id": ["A"], "qty": [1]})
    result = reconcile(contract, shadow, target)
    assert result.summary.match == 1
    assert result.summary.total == 1


def test_draft_and_contract_share_schema():
    # A DraftContract validates into the same shape used by the engine.
    draft = DraftContract(
        comparison_type="x", source_type="s4", target_type="ibp",
        business_key=[{"source_field": "id", "target_field": "id"}],
        source_schema=["id"], target_schema=["id"],
    )
    assert draft.business_key[0].source_field == "id"
