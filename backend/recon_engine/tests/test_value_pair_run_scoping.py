"""Coverage for value_pair_store's provisional/promoted run-scoping (see the
`value_pair_library` DDL comment in storage/db.py): a pairing discovered
mid-run is invisible to other runs until promoted at that run's successful
finalize, or deleted if the run is discarded instead.
"""

from __future__ import annotations

from backend.recon_engine.storage import value_pair_store

_KEY = dict(
    source_connector="s4", target_connector="ibp",
    source_field="Material", target_field="PRDID",
)


def _propose(*, value, target, graph_run_id=None):
    return value_pair_store.propose(
        **_KEY, source_value=value, target_value=target, ops=[], added_by="test",
        graph_run_id=graph_run_id,
    )


def test_a_provisional_pairing_is_invisible_to_other_runs_until_promoted():
    _propose(value="A", target="A1", graph_run_id="run_1")

    # A different run's own lookup doesn't see run_1's still-provisional row.
    other_run = value_pair_store.lookup_pairs(**_KEY, graph_run_id="run_2")
    assert "A" not in other_run

    # No run context (Manual mode / live pairing) doesn't see it either.
    no_context = value_pair_store.lookup_pairs(**_KEY, graph_run_id=None)
    assert "A" not in no_context

    # run_1 itself sees its own provisional row (later batches of the SAME run).
    own_run = value_pair_store.lookup_pairs(**_KEY, graph_run_id="run_1")
    assert "A" in own_run


def test_promote_run_makes_a_pairing_globally_visible():
    _propose(value="A", target="A1", graph_run_id="run_1")
    promoted = value_pair_store.promote_run("run_1")
    assert promoted == 1

    other_run = value_pair_store.lookup_pairs(**_KEY, graph_run_id="run_2")
    assert "A" in other_run
    no_context = value_pair_store.lookup_pairs(**_KEY, graph_run_id=None)
    assert "A" in no_context


def test_discard_run_removes_only_that_runs_still_provisional_rows():
    _propose(value="A", target="A1", graph_run_id="run_1")
    _propose(value="B", target="B1", graph_run_id="run_1")
    # A second run's own pairing must survive run_1's discard.
    _propose(value="C", target="C1", graph_run_id="run_2")
    # A promoted (no-run-context) pairing must also survive.
    _propose(value="D", target="D1", graph_run_id=None)

    removed = value_pair_store.discard_run("run_1")
    assert removed == 2

    # run_1's own now-deleted rows are gone, even from its own lookup — "D" is
    # promoted (no run context), so it correctly remains visible everywhere.
    run_1_view = value_pair_store.lookup_pairs(**_KEY, graph_run_id="run_1")
    assert "A" not in run_1_view
    assert "B" not in run_1_view
    assert "D" in run_1_view
    assert "C" in value_pair_store.lookup_pairs(**_KEY, graph_run_id="run_2")
    assert "D" in value_pair_store.lookup_pairs(**_KEY, graph_run_id=None)


def test_no_run_context_pairing_is_promoted_immediately():
    stored = _propose(value="A", target="A1", graph_run_id=None)
    assert "A" in value_pair_store.lookup_pairs(**_KEY, graph_run_id="any_other_run")
    # Nothing to discard for a run that never proposed anything.
    assert value_pair_store.discard_run("any_other_run") == 0
    assert stored.source_value == "A"


def test_concurrent_discovery_by_a_different_run_promotes_immediately():
    """Two runs independently discovering the identical (source_value,
    target_value) pairing while the first is still in flight: the second
    discovery promotes it immediately (see value_pair_store.propose's
    docstring) rather than leaving it owned by a run that might later be
    discarded out from under the first run's already-resolved results."""
    _propose(value="A", target="A1", graph_run_id="run_1")
    _propose(value="A", target="A1", graph_run_id="run_2")  # same pairing, a different run

    # Now promoted — visible with no run context, and survives run_1's discard.
    assert "A" in value_pair_store.lookup_pairs(**_KEY, graph_run_id=None)
    value_pair_store.discard_run("run_1")
    assert "A" in value_pair_store.lookup_pairs(**_KEY, graph_run_id=None)
