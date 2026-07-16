from __future__ import annotations

import pandas as pd

from backend.recon_engine.matching.product import match_products
from backend.recon_engine.models.value_mapping import Confidence


def _match(mapping, source_value):
    return next(m for m in mapping.matches if m.source_value == source_value)


def test_rule0_out_of_scope_group():
    mapping = match_products(
        source_material=pd.Series(["RAW-1"]),
        source_material_group=pd.Series(["RM"]),
        target_prdid=pd.Series(["RAW-1"]),
    )
    m = _match(mapping, "RAW-1")
    assert m.confidence == Confidence.OUT_OF_SCOPE
    assert m.rule == "product.rule0_group_out_of_scope"
    assert m.target_value is None


def test_rule1_exact_id_group_aligned():
    mapping = match_products(
        source_material=pd.Series(["MAT-1"]),
        source_material_group=pd.Series(["FG"]),
        target_prdid=pd.Series(["MAT-1"]),
        target_prodgroup=pd.Series(["FG"]),
    )
    m = _match(mapping, "MAT-1")
    assert m.confidence == Confidence.VERY_HIGH
    assert m.rule == "product.rule1_exact_id_group_aligned"
    assert m.target_value == "MAT-1"


def test_rule2_exact_id_group_not_aligned():
    mapping = match_products(
        source_material=pd.Series(["MAT-1"]),
        source_material_group=pd.Series(["FG"]),
        target_prdid=pd.Series(["MAT-1"]),
        target_prodgroup=pd.Series(["WHITE"]),
    )
    m = _match(mapping, "MAT-1")
    assert m.confidence == Confidence.HIGH
    assert m.rule == "product.rule2_exact_id"
    assert m.target_value == "MAT-1"


def test_rule3_normalized_identity():
    mapping = match_products(
        source_material=pd.Series(["mat-1"]),
        source_material_group=None,
        target_prdid=pd.Series(["MAT1"]),
    )
    m = _match(mapping, "mat-1")
    assert m.confidence == Confidence.HIGH
    assert m.rule == "product.rule3_normalized_identity"
    assert m.target_value == "MAT1"


def test_rule4_alternate_id_when_reachable():
    mapping = match_products(
        source_material=pd.Series(["ALT-1"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-9"]),
        target_prdiddem=pd.Series(["ALT-1"]),
    )
    m = _match(mapping, "ALT-1")
    assert m.confidence == Confidence.HIGH
    assert m.rule == "product.rule4_alternate_id"
    assert m.target_value == "PRD-9"


def test_rule4_unreachable_when_alt_columns_empty_falls_to_rule6():
    # PRDIDDEM/SPRDID present but entirely blank — exactly the real data shape
    # documented in the module docstring: unreachable, not faked.
    mapping = match_products(
        source_material=pd.Series(["ALT-1"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-9"]),
        target_prdiddem=pd.Series([None]),
        target_sprdid=pd.Series([""]),
    )
    m = _match(mapping, "ALT-1")
    assert m.confidence == Confidence.NONE
    assert m.rule == "product.rule6_no_match"
    assert "rule 4/alternate-id" in m.evidence


def test_rule5_description_bridge_single_candidate():
    # The fix under test: the bridge is SalesOrderItemText -> PRODDESC, NEVER
    # Material -> PRODDESC.
    mapping = match_products(
        source_material=pd.Series(["MAT-X"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-1"]),
        target_proddesc=pd.Series(["Chocolate Bar"]),
        source_order_item_text=pd.Series(["chocolate bar"]),  # case/whitespace variance only
    )
    m = _match(mapping, "MAT-X")
    assert m.confidence == Confidence.MEDIUM
    assert m.rule == "product.rule5_description_match"
    assert m.target_value == "PRD-1"
    assert m.candidates is None


def test_rule5_does_not_bridge_on_the_material_code_itself():
    # Regression guard for the original bug: a Material whose *code* happens to
    # equal a PRODDESC string must NOT match via rule 5 — only its
    # SalesOrderItemText may.
    mapping = match_products(
        source_material=pd.Series(["Chocolate Bar"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-1"]),
        target_proddesc=pd.Series(["Chocolate Bar"]),
        source_order_item_text=pd.Series(["totally unrelated text"]),
    )
    m = _match(mapping, "Chocolate Bar")
    assert m.confidence == Confidence.NONE
    assert m.rule == "product.rule6_no_match"


def test_rule5_ambiguous_description_records_all_candidates():
    mapping = match_products(
        source_material=pd.Series(["MAT-A"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-1", "PRD-2"]),
        target_proddesc=pd.Series(["Dough", "Dough"]),
        source_order_item_text=pd.Series(["dough"]),
    )
    m = _match(mapping, "MAT-A")
    assert m.confidence == Confidence.MEDIUM
    assert m.rule == "product.rule5_description_match_ambiguous"
    assert m.target_value is None
    assert m.candidates == ["PRD-1", "PRD-2"]


def test_rule5_checks_every_distinct_text_for_a_material():
    # MAT-B appears on two order lines with different free text; only one of
    # them happens to match a known PRODDESC.
    mapping = match_products(
        source_material=pd.Series(["MAT-B", "MAT-B"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-7"]),
        target_proddesc=pd.Series(["Meat"]),
        source_order_item_text=pd.Series(["unrelated line text", "meat"]),
    )
    m = _match(mapping, "MAT-B")
    assert m.confidence == Confidence.MEDIUM
    assert m.rule == "product.rule5_description_match"
    assert m.target_value == "PRD-7"
    assert m.row_count == 2


def test_rule5_unreachable_without_order_item_text():
    mapping = match_products(
        source_material=pd.Series(["MAT-X"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-1"]),
        target_proddesc=pd.Series(["Chocolate Bar"]),
        # source_order_item_text omitted entirely
    )
    m = _match(mapping, "MAT-X")
    assert m.confidence == Confidence.NONE
    assert m.rule == "product.rule6_no_match"
    assert "rule 5/description-bridge" in m.evidence


def test_rule6_no_match():
    mapping = match_products(
        source_material=pd.Series(["GHOST"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-1"]),
    )
    m = _match(mapping, "GHOST")
    assert m.confidence == Confidence.NONE
    assert m.rule == "product.rule6_no_match"
    assert m.target_value is None


def test_override_wins_over_every_rule():
    mapping = match_products(
        source_material=pd.Series(["GHOST"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-1"]),
        overrides={"GHOST": "PRD-1"},
    )
    m = _match(mapping, "GHOST")
    assert m.confidence == Confidence.VERY_HIGH
    assert m.rule == "product.override"
    assert m.target_value == "PRD-1"


def test_row_count_reflects_occurrences():
    mapping = match_products(
        source_material=pd.Series(["MAT-1", "MAT-1", "MAT-1"]),
        source_material_group=None,
        target_prdid=pd.Series(["MAT-1"]),
    )
    assert _match(mapping, "MAT-1").row_count == 3


def test_determinism_two_runs_identical():
    kwargs = dict(
        source_material=pd.Series(["MAT-1", "RAW-1", "mat-2", "GHOST"]),
        source_material_group=pd.Series(["FG", "RM", None, None]),
        target_prdid=pd.Series(["MAT-1", "MAT2"]),
        target_prodgroup=pd.Series(["FG", "FG"]),
        target_proddesc=pd.Series(["Widget", "Gadget"]),
        source_order_item_text=pd.Series(["widget", "n/a", "gadget", "mystery"]),
    )
    first = match_products(**kwargs)
    second = match_products(**kwargs)
    assert first.model_dump() == second.model_dump()
