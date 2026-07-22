"""Attribute-mapping library: canonical key, store dedup, and store-back.

Covers the data-modeling requirement the whole feature hinges on — the
canonical composite key must be ORDER-INDEPENDENT so the identical logical
mapping stored in a different column order dedupes to one row and is reused.
"""

from __future__ import annotations

from backend.recon_engine import attribute_library
from backend.recon_engine.canonical import canonical_column_key
from backend.recon_engine.models.attribute_mapping import AttributePair, MappingProvenance
from backend.recon_engine.models.contract import (
    ApprovalStatus,
    BusinessKeyField,
    CompareField,
    TransformationContract,
)
from backend.recon_engine.storage import attribute_mapping_store as store


# ── canonical key ────────────────────────────────────────────────────────────

def test_canonical_key_is_order_independent():
    a = canonical_column_key(["Material", "Plant", "Req.Dlv.Dt"])
    b = canonical_column_key(["Req.Dlv.Dt", "Plant", "Material"])
    assert a == b


def test_canonical_key_trims_and_casefolds():
    assert canonical_column_key([" Material ", "PLANT"]) == canonical_column_key(["material", "plant"])


def test_canonical_key_distinguishes_different_sets():
    assert canonical_column_key(["Material", "Plant"]) != canonical_column_key(["Material", "Region"])


# ── store upsert / dedup / lookup ─────────────────────────────────────────────

def _pairs():
    return [
        AttributePair(source_col="Material", target_col="PRDID", role="key"),
        AttributePair(source_col="Qty", target_col="SALES", role="compare"),
    ]


def test_upsert_then_lookup_hit_any_order():
    store.upsert(
        source_connector="s4", target_connector="ibp", comparison_type="soh",
        source_columns=["Material", "Qty", "Plant"], target_columns=["PRDID", "SALES", "LOCID"],
        mappings=_pairs(), confidence=0.9,
    )
    # look up with the SAME set in a different order → hit
    hit = store.lookup(
        source_connector="s4", target_connector="ibp", comparison_type="soh",
        source_columns=["Plant", "Qty", "Material"], target_columns=["LOCID", "SALES", "PRDID"],
    )
    assert hit is not None
    assert hit.confidence == 0.9
    assert {(p.source_col, p.target_col) for p in hit.mappings} == {("Material", "PRDID"), ("Qty", "SALES")}


def test_upsert_dedupes_and_bumps_version_regardless_of_order():
    first = store.upsert(
        source_connector="s4", target_connector="ibp", comparison_type="soh",
        source_columns=["Material", "Qty"], target_columns=["PRDID", "SALES"],
        mappings=_pairs(), confidence=0.5,
    )
    # identical logical key, columns supplied in a DIFFERENT order + new confidence
    second = store.upsert(
        source_connector="s4", target_connector="ibp", comparison_type="soh",
        source_columns=["Qty", "Material"], target_columns=["SALES", "PRDID"],
        mappings=_pairs(), confidence=0.95,
    )
    assert first.id == second.id  # same row, not a duplicate
    assert second.version == 2  # overwrite + version bump
    assert second.confidence == 0.95  # latest values win
    assert len(store.list_mappings()) == 1


def test_lookup_miss_returns_none():
    assert store.lookup(
        source_connector="s4", target_connector="ibp", comparison_type="soh",
        source_columns=["Nope"], target_columns=["Nada"],
    ) is None


def test_filters_and_delete_and_flush():
    store.upsert(source_connector="s4", target_connector="ibp", comparison_type="soh",
                 source_columns=["A"], target_columns=["B"], mappings=_pairs())
    store.upsert(source_connector="excel", target_connector="excel", comparison_type="inv",
                 source_columns=["C"], target_columns=["D"], mappings=_pairs())

    assert len(store.list_mappings()) == 2
    assert len(store.list_mappings(source_connector="s4")) == 1
    assert len(store.list_mappings(comparison_type="inv")) == 1

    target = store.list_mappings(source_connector="s4")[0]
    assert store.delete(target.id) is True
    assert store.delete(target.id) is False  # already gone
    assert len(store.list_mappings()) == 1

    assert store.flush() == 1
    assert store.list_mappings() == []


# ── store-back from a completed contract ──────────────────────────────────────

def _contract() -> TransformationContract:
    return TransformationContract(
        contract_id="contract_x", contract_version=1,
        comparison_type="soh", source_type="s4", target_type="ibp",
        business_key=[BusinessKeyField(source_field="Material", target_field="PRDID")],
        compare_fields=[CompareField(source_field="Qty", target_field="SALES")],
        source_schema=["Material", "Qty", "Plant"],
        target_schema=["PRDID", "SALES", "LOCID"],
        approval_status=ApprovalStatus.APPROVED,
    )


def test_store_back_from_contract_then_library_result_hit():
    stored = attribute_library.store_back_from_contract(_contract(), "run_1", confidence=0.8)
    assert stored is not None
    assert stored.validated_by_run_id == "run_1"
    assert stored.provenance == MappingProvenance.LIBRARY

    # A tier-1 lookup over the SAME dataset columns (reordered) returns a card.
    result = attribute_library.library_result_for(
        source_connector="s4", target_connector="ibp", comparison_type="soh",
        source_columns=["Plant", "Material", "Qty"], target_columns=["LOCID", "PRDID", "SALES"],
    )
    assert result is not None
    assert result["source"] == "library"
    assert result["provider"] is None  # no LLM was consulted
    assert all(row["provenance"] == "library" for row in result["display"])
    roles = {row["source_col"]: row["role"] for row in result["display"]}
    assert "key" in roles["Material"].lower()
    assert "compare" in roles["Qty"].lower()


def test_store_back_noop_when_no_field_mapping():
    empty = _contract().model_copy(update={"business_key": [], "compare_fields": []})
    assert attribute_library.store_back_from_contract(empty, "run_2") is None
    assert store.list_mappings() == []
