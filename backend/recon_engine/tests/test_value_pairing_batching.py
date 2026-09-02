"""Coverage for distinct-date-union batching (recon_engine.value_pairing.batching)
and its integration into pipeline.pair_values: per-batch source extraction,
cross-batch library reuse (no duplicate LLM call for a recurring value),
final merge/dedup, and the bounded in-process retry on an all-providers-failed
LLM outcome. The LLM is faked throughout (never a real network call).
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.recon_engine.storage import value_pair_store
from backend.recon_engine.value_pairing import pipeline
from backend.recon_engine.value_pairing.batching import build_batches


class _Settings:
    any_llm_configured = True


@pytest.fixture
def configured_llm(monkeypatch):
    monkeypatch.setattr(pipeline, "get_settings", lambda: _Settings())


def _series(values):
    return pd.Series(values)


# ── build_batches ─────────────────────────────────────────────────────────

def test_build_batches_degrades_to_one_batch_without_any_date_column():
    source = _series(["A", "B"])
    target = _series(["X"])
    batches = build_batches(
        source_series=source, target_series=target, source_dates=None, target_dates=None
    )
    assert len(batches) == 1
    label, smask, tmask = batches[0]
    assert label == "All records"
    assert smask.tolist() == [True, True]
    assert tmask.tolist() == [True]


def test_build_batches_partitions_the_union_of_distinct_dates_oldest_first():
    source = _series(["A", "B", "C"])
    source_dates = _series(["2021-01-01", "2023-06-01", "2021-12-31"])
    target = _series(["X"])
    target_dates = _series(["2021-01-01"])
    batches = build_batches(
        source_series=source, target_series=target,
        source_dates=source_dates, target_dates=target_dates,
        max_dates_per_batch=1,
    )
    labels = [label for label, _s, _t in batches]
    assert labels == ["2021-01-01", "2021-12-31", "2023-06-01"]
    first_smask, first_tmask = batches[0][1], batches[0][2]
    assert first_smask.tolist() == [True, False, False]
    assert first_tmask.tolist() == [True], "same calendar date on source and target -> same batch"


def test_build_batches_a_shared_date_lands_both_sides_in_one_slot():
    source = _series(["A"])
    source_dates = _series(["2021-01-01"])
    target = _series(["X", "Y"])
    target_dates = _series(["2021-01-01", "2022-01-01"])
    batches = build_batches(
        source_series=source, target_series=target,
        source_dates=source_dates, target_dates=target_dates,
        max_dates_per_batch=1,
    )
    labels = [label for label, _s, _t in batches]
    assert labels == ["2021-01-01", "2022-01-01"], "date present on only one side still gets its own slot"
    assert batches[0][2].tolist() == [True, False]
    assert batches[0][1].tolist() == [True]


def test_build_batches_adds_a_trailing_undated_batch():
    source = _series(["A", "B"])
    source_dates = _series(["2021-01-01", None])
    target = _series(["X"])
    target_dates = _series(["2021-01-01"])
    batches = build_batches(
        source_series=source, target_series=target,
        source_dates=source_dates, target_dates=target_dates,
    )
    labels = [label for label, _s, _t in batches]
    assert labels[-1] == "Undated"
    assert batches[-1][1].tolist() == [False, True]
    assert batches[-1][2].tolist() == [False]


def test_build_batches_default_cap_is_4000_distinct_dates():
    from backend.recon_engine.value_pairing.batching import DEFAULT_MAX_DATES_PER_BATCH

    assert DEFAULT_MAX_DATES_PER_BATCH == 4000

    source = _series(["A", "B"])
    source_dates = _series(["2021-01-01", "2021-01-02"])
    target = _series(["X"])
    target_dates = _series(["2021-01-01"])
    batches = build_batches(
        source_series=source, target_series=target,
        source_dates=source_dates, target_dates=target_dates,
    )
    assert len(batches) == 1, "2 distinct dates is well under the 4000-date cap -> one batch"


# ── pipeline.pair_values batching integration ────────────────────────────────

def test_recurring_value_across_batches_resolves_once_and_reuses_the_library(
    monkeypatch, configured_llm
):
    """"5001" has one record dated 2021-06-01 and one dated 2023-06-01 — with
    max_dates_per_batch=1 that's two batches, same value. The FIRST batch to
    reach it must do the real LLM work and persist it; the SECOND must reuse
    the library instead of asking the LLM again, and the final merged result
    must be a single row (not one per batch)."""
    call_count = {"n": 0}
    payload = {
        "pairs": [
            {
                "source_value": "5001",
                "target_value": "PL5001",
                "ops": [{"op": "prepend_prefix", "params": {"value": "PL"}}],
                "reason": "PL prefix seen in the target data.",
            }
        ]
    }

    class _CountingClient:
        def complete_json(self, messages):  # noqa: ARG002
            call_count["n"] += 1
            return payload

    monkeypatch.setattr(pipeline, "build_llm_client", lambda: _CountingClient())

    source_series = _series(["5001", "5001"])
    source_dates = _series(["2021-06-01", "2023-06-01"])
    target_series = _series(["PL5001"])

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=source_series,
        target_series=target_series,
        source_connector="s4",
        target_connector="ibp",
        source_dates=source_dates,
        max_dates_per_batch=1,
    )

    assert call_count["n"] == 1, "the second batch must reuse the library, not call the LLM again"
    assert len(result.matches) == 1, "the recurring value must be one merged row, not one per batch"
    match = result.matches[0]
    assert match.target_value == "PL5001"
    assert match.rule == "value_pairing.llm_verified"
    assert match.row_count == 2, "row_count must sum across every batch the value appeared in"


def test_on_batch_callback_reports_every_batch_in_order(configured_llm):
    seen = []
    source_series = _series(["A", "B"])
    source_dates = _series(["2021-01-01", "2023-01-01"])
    target_series = _series(["X"])

    pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=source_series,
        target_series=target_series,
        source_connector="s4",
        target_connector="ibp",
        source_dates=source_dates,
        max_dates_per_batch=1,
        on_batch=lambda progress, matches: seen.append(  # noqa: ARG005
            (progress.batch_index, progress.batch_count, progress.batch_label)
        ),
    )

    assert seen == [(0, 2, "2021-01-01"), (1, 2, "2023-01-01")]


def test_on_batch_callback_reports_target_candidate_count_without_gating_matches(configured_llm):
    """Target dates are batched purely for display: "5001" (source, 2021) must
    still be matchable against an identical target value dated 2023 — a
    different date window — while the reported target_candidate_count for
    the 2021 batch reflects only target rows actually dated 2021 (none).

    Source and target share ONE date-union batch plan (see batching.py's
    module docstring), so 2021-06-01 and 2023-06-01 — two distinct dates —
    are two separate batches under max_dates_per_batch=1; the second batch
    has no source rows of its own (nothing to pair), but is still reported
    via on_batch."""
    seen = []
    source_series = _series(["5001"])
    source_dates = _series(["2021-06-01"])
    target_series = _series(["5001"])  # identical value -> identity match, no LLM needed
    target_dates = _series(["2023-06-01"])  # deliberately a different window than source

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=source_series,
        target_series=target_series,
        source_connector="s4",
        target_connector="ibp",
        source_dates=source_dates,
        target_dates=target_dates,
        max_dates_per_batch=1,
        on_batch=lambda progress, matches: seen.append(progress),  # noqa: ARG005
    )

    assert len(seen) == 2
    assert seen[0].batch_label == "2021-06-01"
    assert seen[0].target_candidate_count == 0, (
        "no target row is dated 2021-06-01"
    )
    assert seen[1].batch_label == "2023-06-01"
    assert seen[1].target_candidate_count == 1, (
        "one target row is dated 2023-06-01"
    )
    assert result.matches[0].target_value == "5001", (
        "the match itself must still happen — target batching never gates matching"
    )


class _FakeOutcome:
    def __init__(self, all_failed: bool) -> None:
        self.all_failed = all_failed


def test_batch_retries_bounded_times_then_raises_when_configured_to(monkeypatch, configured_llm):
    attempts = {"n": 0}

    def _always_fails():
        attempts["n"] += 1
        return _FakeOutcome(all_failed=True)

    monkeypatch.setattr(pipeline, "reset_llm_outcome", lambda: None)
    monkeypatch.setattr(pipeline, "get_last_llm_outcome", _always_fails)
    monkeypatch.setattr(pipeline, "build_llm_client", lambda: (_ for _ in ()).throw(AssertionError("never reached")))

    with pytest.raises(pipeline.ValuePairingUnavailable):
        pipeline.pair_values(
            source_field="Material",
            target_field="PRDID",
            source_series=_series(["RAW-1"]),
            target_series=_series(["PRD-1"]),
            source_connector="s4",
            target_connector="ibp",
            raise_on_batch_failure=True,
        )
    assert attempts["n"] == pipeline.MAX_BATCH_LLM_RETRIES + 1


def test_batch_recovers_if_a_retry_succeeds(monkeypatch, configured_llm):
    outcomes = iter([True, True, False])  # fails twice, then the outcome clears

    monkeypatch.setattr(pipeline, "reset_llm_outcome", lambda: None)
    monkeypatch.setattr(pipeline, "get_last_llm_outcome", lambda: _FakeOutcome(all_failed=next(outcomes)))
    monkeypatch.setattr(pipeline, "build_llm_client", lambda: _FakeClientEmpty())

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["RAW-1"]),
        target_series=_series(["PRD-1"]),
        source_connector="s4",
        target_connector="ibp",
        raise_on_batch_failure=True,
    )
    match = result.matches[0]
    assert match.rule == "value_pairing.unpaired"  # no exception — recovered, just nothing proposed


class _FakeClientEmpty:
    def complete_json(self, messages):  # noqa: ARG002
        return {"pairs": []}


def test_manual_mode_default_degrades_instead_of_raising_on_permanent_batch_failure(
    monkeypatch, configured_llm
):
    monkeypatch.setattr(pipeline, "reset_llm_outcome", lambda: None)
    monkeypatch.setattr(pipeline, "get_last_llm_outcome", lambda: _FakeOutcome(all_failed=True))
    monkeypatch.setattr(pipeline, "build_llm_client", lambda: _FakeClientEmpty())

    # raise_on_batch_failure defaults to False (Manual mode's contract) — must
    # never raise, even after exhausting retries.
    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=_series(["RAW-1"]),
        target_series=_series(["PRD-1"]),
        source_connector="s4",
        target_connector="ibp",
    )
    assert result.matches[0].rule == "value_pairing.unpaired"


def test_corroboration_unaffected_by_an_unrelated_batch(monkeypatch, configured_llm):
    """"5001" and "01" are both dated 2024 (same batch) and reproduce the
    original single-pass ambiguous-candidate/corroboration scenario exactly;
    "FILLER" is dated 2050 purely to force a SECOND, unrelated batch to exist
    in this same run. Its presence — and pattern-reuse being scoped to its
    OWN batch, never "5001"'s — must not change "01"'s corroboration outcome
    at all, since source_series/source_dates/target_series/target_dates are
    always passed into candidate resolution UNSLICED regardless of batch."""
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

    class _FakeClient:
        def complete_json(self, messages):  # noqa: ARG002
            return payload

    monkeypatch.setattr(pipeline, "build_llm_client", lambda: _FakeClient())

    source_series = _series(["5001", "01", "FILLER"])
    source_dates = _series(["2024-01-01", "2024-03-01", "2050-01-01"])
    target_series = _series(["PL5001@S21400", "PL01@S21400", "01", "FILLER-TARGET"])
    target_dates = _series(["2024-01-01", "2024-03-01", "2099-01-01", "2050-01-01"])

    result = pipeline.pair_values(
        source_field="Material",
        target_field="PRDID",
        source_series=source_series,
        target_series=target_series,
        source_connector="s4",
        target_connector="ibp",
        source_dates=source_dates,
        target_dates=target_dates,
        max_dates_per_batch=2,  # 2024-01-01 + 2024-03-01 share a batch; 2050-01-01 forced into a second
    )
    plant_matches = {m.target_value: m for m in result.matches if m.source_value == "01"}
    assert set(plant_matches) == {"01", "PL01@S21400"}
    assert plant_matches["01"].corroboration is False  # dates checked, disjoint (2024 vs 2099)
    assert plant_matches["PL01@S21400"].corroboration is True  # dates checked, overlap (both 2024-03-01)
