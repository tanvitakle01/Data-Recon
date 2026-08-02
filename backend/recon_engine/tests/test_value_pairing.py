"""Coverage for the LLM-driven value-pairing pipeline (recon_engine.value_pairing).

Exercises: distinct-value extraction, the identity pre-pass, deterministic
verification of an ORDERED chain of ops, and the full pipeline's outcomes —
library-reused pairings, an uncontested identity match, a multi-step LLM chain
verified for one value and mechanically reused for another (no second LLM
call), a rejected LLM claim, an ambiguous identity-vs-transform competition
resolved by date-overlap corroboration, and a genuinely unpaired value. The
LLM is faked throughout (never a real network call).
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.recon_engine.storage import value_pair_store
from backend.recon_engine.value_pairing import pipeline
from backend.recon_engine.value_pairing.corroborate import corroboration_overlap
from backend.recon_engine.value_pairing.extraction import distinct_values
from backend.recon_engine.value_pairing.identity import identity_prepass
from backend.recon_engine.value_pairing.verify import (
    verify_chain,
    verify_chain_bidirectional,
    verify_pair,
)


def test_distinct_values_drops_blanks_and_counts_rows():
    series = pd.Series(["A", "A", "B", None, "  ", ""])
    assert distinct_values(series) == {"A": 2, "B": 1}


def test_identity_prepass_splits_matched_and_residual():
    pairs, residual_source, residual_target = identity_prepass({"A", "B"}, {"A", "C"})
    assert pairs == {"A": "A"}
    assert residual_source == {"B"}
    assert residual_target == {"C"}


def test_verify_pair_passes_when_transform_reproduces_the_target():
    ok, produced = verify_pair("prepend_prefix", {"value": "PL"}, "Plant", "5006")
    assert ok is True
    assert produced == "PL5006"


def test_verify_chain_applies_steps_in_order():
    ops = [
        {"op": "prepend_prefix", "params": {"value": "PL"}},
        {"op": "append_suffix", "params": {"value": "@S21400"}},
    ]
    ok, produced = verify_chain(ops, "Plant", "5006")
    assert ok is True
    assert produced == "PL5006@S21400"


def test_verify_chain_rejects_an_empty_chain():
    ok, reason = verify_chain([], "Plant", "5006")
    assert ok is False
    assert "empty" in reason


def test_verify_chain_rejects_an_unknown_op_mid_chain():
    ops = [
        {"op": "prepend_prefix", "params": {"value": "PL"}},
        {"op": "not_a_real_op", "params": {}},
    ]
    ok, reason = verify_chain(ops, "Plant", "5006")
    assert ok is False
    assert "not in the allow-listed registry" in reason


def test_verify_chain_rejects_missing_required_params():
    ok, reason = verify_chain([{"op": "prepend_prefix", "params": {}}], "Plant", "5006")
    assert ok is False
    assert "value" in reason


def test_verify_chain_bidirectional_forward():
    ops = [{"op": "remove_leading_zeros", "params": {"min_width": 2}}]
    ok, direction = verify_chain_bidirectional(ops, "Material", "FG0006", "FG06")
    assert ok is True
    assert direction == "forward"


def test_verify_chain_bidirectional_reverse():
    # The TARGET is the over-padded side here — the chain only verifies when
    # applied to value_b (the claimed target) and compared back to value_a.
    ops = [{"op": "remove_leading_zeros", "params": {"min_width": 2}}]
    ok, direction = verify_chain_bidirectional(ops, "Material", "FG06", "FG0006")
    assert ok is True
    assert direction == "reverse"


def test_verify_chain_bidirectional_neither_direction_verifies():
    ops = [{"op": "remove_leading_zeros", "params": {"min_width": 2}}]
    ok, direction = verify_chain_bidirectional(ops, "Material", "FG06", "FG0007")
    assert ok is False
    assert direction == ""


def test_corroboration_overlap_none_without_date_columns():
    keys = pd.Series(["5006"])
    assert (
        corroboration_overlap(
            source_keys=keys, source_dates=None, source_value="5006",
            target_keys=keys, target_dates=None, target_value="5006",
        )
        is None
    )


def test_corroboration_overlap_true_when_dates_match():
    source_keys = pd.Series(["5006", "5006"])
    source_dates = pd.Series(["2024-01-01", "2024-01-02"])
    target_keys = pd.Series(["PL5006"])
    target_dates = pd.Series(["2024-01-02"])
    assert (
        corroboration_overlap(
            source_keys=source_keys, source_dates=source_dates, source_value="5006",
            target_keys=target_keys, target_dates=target_dates, target_value="PL5006",
        )
        is True
    )


def test_corroboration_overlap_false_when_dates_disjoint():
    source_keys = pd.Series(["5006"])
    source_dates = pd.Series(["2024-01-01"])
    target_keys = pd.Series(["PL5006"])
    target_dates = pd.Series(["2024-06-01"])
    assert (
        corroboration_overlap(
            source_keys=source_keys, source_dates=source_dates, source_value="5006",
            target_keys=target_keys, target_dates=target_dates, target_value="PL5006",
        )
        is False
    )


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    def complete_json(self, messages):  # noqa: ARG002
        return self._payload


class _Settings:
    any_llm_configured = True
    value_pairing_window_years = 2


@pytest.fixture
def configured_llm(monkeypatch):
    """Report an LLM as configured without needing real credentials."""
    monkeypatch.setattr(pipeline, "get_settings", lambda: _Settings())


def _series(values):
    return pd.Series(values)


def test_pipeline_identity_match_resolves_without_any_llm_call(monkeypatch, configured_llm):
    def _boom():
        raise AssertionError("an uncontested identity match must never call the LLM")

    monkeypatch.setattr(pipeline, "build_llm_client", _boom)

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["MAT-1"]),
        target_series=_series(["MAT-1"]),
        source_connector="s4",
        target_connector="ibp",
    )
    match = result.matches[0]
    assert match.confidence.value == "very_high"
    assert match.rule == "value_pairing.identity"
    assert match.target_value == "MAT-1"


def test_pipeline_library_reused_pair_resolves_without_any_llm_call(monkeypatch, configured_llm):
    value_pair_store.propose(
        source_connector="s4",
        target_connector="ibp",
        source_field="Material",
        target_field="PRDID",
        source_value="5006",
        target_value="PL5006",
        ops=[{"op": "prepend_prefix", "params": {"value": "PL"}}],
    )

    def _boom():
        raise AssertionError("a library-stored value must never call the LLM")

    monkeypatch.setattr(pipeline, "build_llm_client", _boom)

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["5006"]),
        target_series=_series(["PL5006"]),
        source_connector="s4",
        target_connector="ibp",
    )
    match = result.matches[0]
    assert match.confidence.value == "high"
    assert match.rule == "value_pairing.library_reused"
    assert match.target_value == "PL5006"


def test_deterministic_only_resolves_identity_match_without_any_llm_call(monkeypatch, configured_llm):
    def _boom():
        raise AssertionError("pair_values_deterministic_only must never call the LLM")

    monkeypatch.setattr(pipeline, "build_llm_client", _boom)

    result = pipeline.pair_values_deterministic_only(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["MAT-1"]),
        target_series=_series(["MAT-1"]),
        source_connector="s4",
        target_connector="ibp",
    )
    match = result.matches[0]
    assert match.confidence.value == "very_high"
    assert match.rule == "value_pairing.identity"
    assert match.target_value == "MAT-1"


def test_deterministic_only_resolves_library_pair_without_any_llm_call(monkeypatch, configured_llm):
    value_pair_store.propose(
        source_connector="s4",
        target_connector="ibp",
        source_field="Material",
        target_field="PRDID",
        source_value="5006",
        target_value="PL5006",
        ops=[{"op": "prepend_prefix", "params": {"value": "PL"}}],
    )

    def _boom():
        raise AssertionError("pair_values_deterministic_only must never call the LLM")

    monkeypatch.setattr(pipeline, "build_llm_client", _boom)

    result = pipeline.pair_values_deterministic_only(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["5006"]),
        target_series=_series(["PL5006"]),
        source_connector="s4",
        target_connector="ibp",
    )
    match = result.matches[0]
    assert match.confidence.value == "high"
    assert match.rule == "value_pairing.library_reused"
    assert match.target_value == "PL5006"


def test_deterministic_only_leaves_a_value_unpaired_with_no_library_or_identity_hit(configured_llm):
    # No LLM client configured/monkeypatched at all here — proves the residual
    # path never even attempts one; a value with neither a library entry nor
    # an identity match is reported unpaired, exactly like pair_values would
    # for the same residual value if the LLM proposed nothing for it.
    result = pipeline.pair_values_deterministic_only(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["RAW-1"]),
        target_series=_series(["PRD-1"]),
        source_connector="s4",
        target_connector="ibp",
    )
    match = result.matches[0]
    assert match.confidence.value == "none"
    assert match.rule == "value_pairing.unpaired"
    assert match.target_value is None


def test_pipeline_verifies_a_multistep_chain_and_reuses_it_for_another_value(monkeypatch, configured_llm):
    # Only "5001" is explicitly proposed by the (faked) LLM; "7000" has no
    # identity match and the LLM never mentions it. It should still resolve
    # via the SAME confirmed chain, mechanically reused, with no second LLM
    # call needed for it.
    payload = {
        "pairs": [
            {
                "source_value": "5001",
                "target_value": "PL5001@S21400",
                "ops": [
                    {"op": "prepend_prefix", "params": {"value": "PL"}},
                    {"op": "append_suffix", "params": {"value": "@S21400"}},
                ],
                "reason": "PL prefix + @S21400 suffix seen elsewhere in the target data.",
            }
        ]
    }
    monkeypatch.setattr(pipeline, "build_llm_client", lambda: _FakeClient(payload))

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["5001", "7000"]),
        target_series=_series(["PL5001@S21400", "PL7000@S21400"]),
        source_connector="s4",
        target_connector="ibp",
    )
    by_value = {m.source_value: m for m in result.matches}

    assert by_value["5001"].rule == "value_pairing.llm_verified"
    assert by_value["5001"].target_value == "PL5001@S21400"
    assert by_value["5001"].confidence.value == "high"
    assert by_value["5001"].library_id is not None

    assert by_value["7000"].rule == "value_pairing.pattern_reused"
    assert by_value["7000"].target_value == "PL7000@S21400"
    assert by_value["7000"].confidence.value == "high"
    assert by_value["7000"].library_id is not None

    stored = value_pair_store.get(by_value["7000"].library_id)
    assert stored is not None
    assert stored.ops == payload["pairs"][0]["ops"]


def test_pipeline_verifies_and_reuses_a_reverse_direction_chain(monkeypatch, configured_llm):
    # The TARGET side is the zero-padded one here (FG0006/FG0007 vs FG06/FG07)
    # — the chain only verifies in the "reverse" direction (applied to the
    # target, reduced down to the source). Only "FG06" is explicitly proposed;
    # "FG07" must still resolve via the SAME chain, mechanically reused in the
    # same (reverse) direction, with no second LLM call.
    payload = {
        "pairs": [
            {
                "source_value": "FG06",
                "target_value": "FG0006",
                "ops": [{"op": "remove_leading_zeros", "params": {"min_width": 2}}],
                "reason": "Target keeps 4-digit zero-padding; source uses 2.",
            }
        ]
    }
    monkeypatch.setattr(pipeline, "build_llm_client", lambda: _FakeClient(payload))

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["FG06", "FG07"]),
        target_series=_series(["FG0006", "FG0007"]),
        source_connector="s4",
        target_connector="ibp",
    )
    by_value = {m.source_value: m for m in result.matches}

    assert by_value["FG06"].rule == "value_pairing.llm_verified"
    assert by_value["FG06"].target_value == "FG0006"
    assert by_value["FG06"].confidence.value == "high"

    assert by_value["FG07"].rule == "value_pairing.pattern_reused"
    assert by_value["FG07"].target_value == "FG0007"
    assert by_value["FG07"].confidence.value == "high"


def test_pipeline_rejects_a_wrong_llm_claim(monkeypatch, configured_llm):
    payload = {
        "pairs": [
            {
                "source_value": "5006",
                "target_value": "PL5006",  # claimed target does not exist on the target side
                "ops": [{"op": "prepend_prefix", "params": {"value": "PL"}}],
                "reason": "guess",
            }
        ]
    }
    monkeypatch.setattr(pipeline, "build_llm_client", lambda: _FakeClient(payload))

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["5006"]),
        target_series=_series(["SOMETHING-ELSE"]),
        source_connector="s4",
        target_connector="ibp",
    )
    match = result.matches[0]
    assert match.confidence.value == "none"
    assert match.rule == "value_pairing.llm_rejected"
    assert match.target_value is None

    # A rejected claim is never written to the library.
    assert value_pair_store.lookup_pairs(
        source_connector="s4", target_connector="ibp", source_field="Material", target_field="PRDID"
    ) == {}


def test_pipeline_leaves_a_value_unpaired_when_the_llm_proposes_nothing(monkeypatch, configured_llm):
    monkeypatch.setattr(pipeline, "build_llm_client", lambda: _FakeClient({"pairs": []}))

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["RAW-1"]),
        target_series=_series(["PRD-1"]),
        source_connector="s4",
        target_connector="ibp",
    )
    match = result.matches[0]
    assert match.confidence.value == "none"
    assert match.rule == "value_pairing.unpaired"
    assert match.target_value is None


def test_pipeline_never_calls_the_llm_when_no_provider_is_configured():
    # The autouse isolated_store fixture clears GROQ_API_KEY/OPENAI_API_KEY, so
    # get_settings().any_llm_configured is False here — no monkeypatch needed.
    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["RAW-1"]),
        target_series=_series(["PRD-1"]),
        source_connector="s4",
        target_connector="ibp",
    )
    match = result.matches[0]
    assert match.rule == "value_pairing.unpaired"


def test_pipeline_accepts_both_candidates_and_labels_corroboration(monkeypatch, configured_llm):
    # "01" coincidentally equals a real (but unrelated) target value AND the
    # chain confirmed from "5001" (prepend "PL" + append "@S21400") ALSO
    # produces a real target for it ("PL01@S21400"). Both are verified
    # candidates for the SAME source value — the pipeline does not force a
    # single winner (reconciliation's per-record date + quantity compare is
    # the real arbiter); it accepts both and attaches the date-overlap
    # corroboration signal to each as a ranking/labeling hint.
    payload = {
        "pairs": [
            {
                "source_value": "5001",
                "target_value": "PL5001@S21400",
                "ops": [
                    {"op": "prepend_prefix", "params": {"value": "PL"}},
                    {"op": "append_suffix", "params": {"value": "@S21400"}},
                ],
                "reason": "PL prefix + @S21400 suffix.",
            }
        ]
    }
    monkeypatch.setattr(pipeline, "build_llm_client", lambda: _FakeClient(payload))

    source_series = pd.Series(["5001", "01"])
    source_dates = pd.Series(["2024-01-01", "2024-03-01"])
    target_series = pd.Series(["PL5001@S21400", "PL01@S21400", "01"])
    target_dates = pd.Series(["2024-01-01", "2024-03-01", "2099-01-01"])

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=source_series,
        target_series=target_series,
        source_connector="s4",
        target_connector="ibp",
        source_dates=source_dates,
        target_dates=target_dates,
    )
    plant_matches = {m.target_value: m for m in result.matches if m.source_value == "01"}
    assert set(plant_matches) == {"01", "PL01@S21400"}

    identity_match = plant_matches["01"]
    assert identity_match.confidence.value == "very_high"
    assert identity_match.rule == "value_pairing.identity"
    assert identity_match.corroboration is False  # dates checked, disjoint

    transform_match = plant_matches["PL01@S21400"]
    assert transform_match.confidence.value == "high"
    assert transform_match.rule == "value_pairing.pattern_reused"
    assert transform_match.corroboration is True  # dates checked, overlap

    assert identity_match.candidates == sorted(["01", "PL01@S21400"])
    assert transform_match.candidates == sorted(["01", "PL01@S21400"])


def test_pipeline_accepts_both_candidates_when_corroboration_has_no_signal(monkeypatch, configured_llm):
    payload = {
        "pairs": [
            {
                "source_value": "5001",
                "target_value": "PL5001@S21400",
                "ops": [
                    {"op": "prepend_prefix", "params": {"value": "PL"}},
                    {"op": "append_suffix", "params": {"value": "@S21400"}},
                ],
                "reason": "PL prefix + @S21400 suffix.",
            }
        ]
    }
    monkeypatch.setattr(pipeline, "build_llm_client", lambda: _FakeClient(payload))

    # No date columns at all -> corroboration always reports "no signal" for
    # every candidate. That must never suppress a candidate — both are still
    # accepted, just with an "unknown" corroboration label.
    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["5001", "01"]),
        target_series=_series(["PL5001@S21400", "PL01@S21400", "01"]),
        source_connector="s4",
        target_connector="ibp",
    )
    plant_matches = {m.target_value: m for m in result.matches if m.source_value == "01"}
    assert set(plant_matches) == {"01", "PL01@S21400"}
    for match in plant_matches.values():
        assert match.corroboration is None
        assert match.confidence.value in {"very_high", "high"}
        assert match.candidates == sorted(["01", "PL01@S21400"])
