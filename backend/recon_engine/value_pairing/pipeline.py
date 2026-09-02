"""Orchestrates the value-pairing pipeline: library lookup, candidate
generation (identity + reused chains + fresh LLM chains), mandatory
verification, and corroboration when candidates compete.

Every verified pairing is persisted to the value-pair library automatically —
this module's output is the same ``ValueMapping`` shape the retired
``matching.product``/``matching.location`` produced, so ``engine.executor``
and ``models.contract`` need no changes at all.

Design note — why identity is a CANDIDATE, not an auto-accept: an exact
string match can be coincidental (a source code that happens to collide with
an unrelated target id) rather than semantic. Locking onto it immediately
would hide a real transform-based pairing for the same value. So every value
gets its full candidate set — identity (if any) plus every transform chain
confirmed to work for it, whether that chain was proposed by the LLM for THIS
value or for a DIFFERENT value this run — before anything is decided. A sole
candidate resolves immediately (still cheap).

Design note — why competing candidates are NOT forced to a single winner:
a source value can genuinely and correctly carry more than one verified
target candidate (e.g. both an identity match and a real transform-based
match). Reconciliation's per-record date + quantity compare is the actual
arbiter — a spurious candidate simply produces no Match for any given real
record, so tolerating ambiguity at the mapping stage is fine. Every verified
candidate is therefore accepted (HIGH confidence, reaches the shadow/join).
Date-overlap corroboration is computed per candidate and attached as a
CONFIDENCE SIGNAL (``ValueMatch.corroboration``) for the reviewer to rank/
label by — never as a filter that suppresses a candidate.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from backend.recon_engine.config import get_settings
from backend.recon_engine.llm import build_llm_client, get_last_llm_outcome, reset_llm_outcome
from backend.recon_engine.models.value_mapping import Confidence, ValueMapping, ValueMatch
from backend.recon_engine.storage import value_pair_store
from backend.recon_engine.value_pairing.batching import (
    DEFAULT_MAX_DATES_PER_BATCH,
    BatchProgress,
    build_batches,
)
from backend.recon_engine.value_pairing.corroborate import corroboration_overlap
from backend.recon_engine.value_pairing.extraction import distinct_values
from backend.recon_engine.value_pairing.identity import identity_prepass
from backend.recon_engine.value_pairing.prompt import build_messages, parse_candidates
from backend.recon_engine.value_pairing.verify import verify_chain, verify_chain_bidirectional

logger = logging.getLogger("recon.value_pairing")

_Chain = list[dict[str, Any]]

# Bounded in-process retry for a batch whose LLM proposal call finds every
# configured provider unavailable (see ``get_last_llm_outcome().all_failed``)
# — 2 retries (3 attempts total) before that batch's residual is either
# hard-stopped (Auto mode, ``raise_on_batch_failure=True``) or left to degrade
# to unpaired (Manual mode's default) exactly like a normal "LLM proposed
# nothing" outcome. No cross-run/checkpointed retry exists here — see
# ``ValuePairingUnavailable``.
MAX_BATCH_LLM_RETRIES = 2


class ValuePairingUnavailable(RuntimeError):
    """A batch's LLM proposal call found every configured provider
    unavailable, even after :data:`MAX_BATCH_LLM_RETRIES` retries.

    Only ever raised when the caller opts in via
    ``pair_values(raise_on_batch_failure=True)`` (Auto mode) — Manual mode's
    ``/value-mapping/run`` never raises this; it leaves the batch's residual
    values unpaired, same as :func:`pair_values`'s existing degrade-on-LLM-
    failure contract.
    """


def _chain_key(ops: _Chain) -> tuple:
    return tuple((step["op"], tuple(sorted(step["params"].items()))) for step in ops)


def _format_chain(ops: _Chain) -> str:
    return " -> ".join(f"{step['op']}({step['params']!r})" for step in ops)


def _propose_llm_chains(
    *,
    candidate_source: list[str],
    candidate_target: list[str],
    exact_matches: dict[str, str],
    mapping_sheet_context: Any,
) -> list[dict[str, Any]]:
    """LLM transformation-discovery pairing. Never raises — degrades to no candidates.

    ``candidate_source`` is the COMPLETE distinct source list minus only
    values already stored in the library (Transformation Discovery: the LLM
    must see exact-matched values too, so it can identify an additional valid
    transform for them — see ``prompt.py``). ``exact_matches`` is passed
    through as context; the caller (``pair_values``) is responsible for
    dropping any returned pair that just restates one, regardless of what the
    model claims.
    """
    if not candidate_source or not candidate_target:
        return []
    if not get_settings().any_llm_configured:
        return []
    try:
        client = build_llm_client()
        payload = client.complete_json(
            build_messages(
                candidate_source=candidate_source,
                candidate_target=candidate_target,
                exact_matches=exact_matches,
                mapping_sheet_context=mapping_sheet_context,
            )
        )
    except Exception as exc:  # noqa: BLE001 — degradation is the contract
        logger.warning("LLM value-pairing failed; leaving residual values unpaired. %s", exc)
        return []
    return parse_candidates(payload)


def _propose_llm_chains_with_retry(
    *,
    candidate_source: list[str],
    candidate_target: list[str],
    exact_matches: dict[str, str],
    mapping_sheet_context: Any,
    batch_label: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Like :func:`_propose_llm_chains`, but retries up to
    :data:`MAX_BATCH_LLM_RETRIES` more times when EVERY configured provider
    failed (``get_last_llm_outcome().all_failed``) — never when the LLM
    simply had nothing to propose (``candidate_source`` empty, or no provider
    configured at all; both leave the outcome unset, so no retry fires).

    Returns ``(candidates, all_failed_after_retries)`` — the caller decides
    whether ``all_failed_after_retries`` should hard-stop (Auto mode) or
    degrade this batch's residual to unpaired (Manual mode's default), same
    as any other "LLM proposed nothing" outcome.
    """
    attempt = 0
    while True:
        reset_llm_outcome()
        candidates = _propose_llm_chains(
            candidate_source=candidate_source,
            candidate_target=candidate_target,
            exact_matches=exact_matches,
            mapping_sheet_context=mapping_sheet_context,
        )
        outcome = get_last_llm_outcome()
        all_failed = bool(outcome is not None and outcome.all_failed)
        if not all_failed or attempt >= MAX_BATCH_LLM_RETRIES:
            return candidates, all_failed
        attempt += 1
        logger.warning(
            "Value-pairing batch %r: all configured LLM providers failed "
            "(attempt %d/%d) — retrying.",
            batch_label, attempt, MAX_BATCH_LLM_RETRIES + 1,
        )


def _finalize_single(
    *,
    value: str,
    target: str,
    origins: list[tuple[str, _Chain]],
    row_count: int,
    source_connector: str,
    target_connector: str,
    source_field: str,
    target_field: str,
    actor: str,
    rule_override: str | None = None,
    evidence_prefix: str = "",
    corroboration: bool | None = None,
    sibling_candidates: list[str] | None = None,
    library_pairs: dict[str, Any] | None = None,
    graph_run_id: str | None = None,
) -> ValueMatch:
    """The resolution for one (value, target) pair — sole candidate or one of
    several accepted candidates (see module docstring)."""
    kinds = {origin for origin, _chain in origins}

    if "identity" in kinds:
        # An exact match must never be superseded by a transform/pattern
        # candidate that ALSO resolved to this same target — both are kept as
        # coexisting evidence (see module docstring), but the identity match's
        # provenance/confidence is reported, not silently downgraded to the
        # transform's.
        extra = kinds - {"identity"}
        evidence = evidence_prefix + f"Exact match: {value!r} == {target!r}."
        if extra:
            evidence += f" Also corroborated by a verified transform ({', '.join(sorted(extra))})."
        return ValueMatch(
            source_value=value,
            target_value=target,
            confidence=Confidence.VERY_HIGH,
            rule=rule_override or "value_pairing.identity",
            evidence=evidence,
            row_count=row_count,
            corroboration=corroboration,
            candidates=sibling_candidates,
        )

    if kinds == {"library"}:
        # Trusted, immediate, no re-verification — this exact pairing was
        # already verified and stored on a prior run. Still routed through
        # the normal candidate machinery (rather than short-circuited in
        # Step 0) so a genuinely competing candidate for the same value (e.g.
        # a coincidental identity match) is never silently discarded just
        # because a different transform was already stored for it.
        hit = (library_pairs or {}).get(value)
        added_on = hit.added_on if hit is not None else None
        chain = next((c for _origin, c in origins if c), [])
        return ValueMatch(
            source_value=value,
            target_value=target,
            confidence=Confidence.HIGH,
            rule=rule_override or "value_pairing.library_reused",
            evidence=(
                evidence_prefix
                + f"Reused a stored value pair from the library "
                f"({_format_chain(chain)}, added {added_on})."
            ),
            row_count=row_count,
            corroboration=corroboration,
            candidates=sibling_candidates,
        )

    # A transform (fresh LLM chain and/or a chain reused from another value)
    # resolved this value — a NEW source_value pairing, worth persisting to
    # the library even when the chain pattern itself was already confirmed
    # elsewhere this run.
    chain = next((c for _origin, c in origins if c), [])
    stored = value_pair_store.propose(
        source_connector=source_connector,
        target_connector=target_connector,
        source_field=source_field,
        target_field=target_field,
        source_value=value,
        target_value=target,
        ops=chain,
        evidence={"origins": sorted(kinds)},
        added_by=actor,
        graph_run_id=graph_run_id,
    )
    origin_label = "llm_verified" if "llm" in kinds else "pattern_reused"
    return ValueMatch(
        source_value=value,
        target_value=target,
        confidence=Confidence.HIGH,
        rule=rule_override or f"value_pairing.{origin_label}",
        evidence=evidence_prefix + f"Verified transform {_format_chain(chain)}: {value!r} -> {target!r}.",
        row_count=row_count,
        library_id=stored.id,
        corroboration=corroboration,
        candidates=sibling_candidates,
    )


def _overlap_label(overlap: bool | None) -> str:
    if overlap is True:
        return "yes"
    if overlap is False:
        return "no"
    return "unknown"


def _resolve_candidates(
    *,
    value: str,
    row_count: int,
    candidates: dict[str, list[tuple[str, _Chain]]],
    source_series: pd.Series,
    target_series: pd.Series,
    source_dates: pd.Series | None,
    target_dates: pd.Series | None,
    source_connector: str,
    target_connector: str,
    source_field: str,
    target_field: str,
    actor: str,
    library_pairs: dict[str, Any] | None = None,
    graph_run_id: str | None = None,
) -> list[ValueMatch]:
    """Resolve every distinct candidate target for ``value`` — a sole
    candidate resolves directly; multiple verified candidates are ALL
    accepted (see module docstring), each carrying its own date-overlap
    corroboration signal rather than being forced to a single winner."""
    distinct_targets = list(candidates)

    if len(distinct_targets) == 1:
        target = distinct_targets[0]
        return [
            _finalize_single(
                value=value,
                target=target,
                origins=candidates[target],
                row_count=row_count,
                source_connector=source_connector,
                target_connector=target_connector,
                source_field=source_field,
                target_field=target_field,
                actor=actor,
                library_pairs=library_pairs,
                graph_run_id=graph_run_id,
            )
        ]

    # Multiple verified candidates for DIFFERENT targets — accept every one
    # of them (reconciliation's per-record date + quantity compare is the
    # real arbiter; a spurious candidate just won't produce a Match for any
    # given row). Date-overlap corroboration is computed per candidate and
    # attached as a ranking/labeling signal, never as a filter.
    overlaps = {
        target: corroboration_overlap(
            source_keys=source_series,
            source_dates=source_dates,
            source_value=value,
            target_keys=target_series,
            target_dates=target_dates,
            target_value=target,
        )
        for target in distinct_targets
    }
    detail = "; ".join(f"{t} (overlap={_overlap_label(overlaps[t])})" for t in distinct_targets)
    siblings = sorted(distinct_targets)

    return [
        _finalize_single(
            value=value,
            target=target,
            origins=candidates[target],
            row_count=row_count,
            source_connector=source_connector,
            target_connector=target_connector,
            source_field=source_field,
            target_field=target_field,
            actor=actor,
            evidence_prefix=f"Multiple candidates for {value!r} ({detail}). ",
            corroboration=overlaps[target],
            sibling_candidates=siblings,
            library_pairs=library_pairs,
            graph_run_id=graph_run_id,
        )
        for target in distinct_targets
    ]


def _assemble_and_resolve(
    *,
    unresolved: dict[str, int],
    library_pairs: dict[str, Any],
    identity_candidate: dict[str, str],
    llm_result_by_value: dict[str, dict[str, Any]],
    pattern_candidates: dict[str, list[tuple[str, _Chain]]],
    llm_rejection_by_value: dict[str, str],
    source_series: pd.Series,
    target_series: pd.Series,
    source_dates: pd.Series | None,
    target_dates: pd.Series | None,
    source_connector: str,
    target_connector: str,
    source_field: str,
    target_field: str,
    actor: str,
    graph_run_id: str | None = None,
) -> list[ValueMatch]:
    """Assemble every distinct candidate target per still-unresolved value
    (from whichever origins are non-empty — library/identity always, LLM/
    pattern only when a caller actually ran that step) and resolve each via
    :func:`_resolve_candidates`. Shared by :func:`pair_values` (all origins)
    and :func:`pair_values_deterministic_only` (library+identity only, empty
    dicts for the rest — no LLM step ever ran, so nothing here needs one)."""
    matches: list[ValueMatch] = []
    for value in list(unresolved):
        row_count = unresolved.pop(value)
        candidates: dict[str, list[tuple[str, _Chain]]] = {}

        if value in library_pairs:
            candidates.setdefault(library_pairs[value].target_value, []).append(("library", library_pairs[value].ops))
        if value in identity_candidate:
            candidates.setdefault(identity_candidate[value], []).append(("identity", []))
        if value in llm_result_by_value:
            info = llm_result_by_value[value]
            candidates.setdefault(info["target"], []).append(("llm", info["chain"]))
        for target, chain in pattern_candidates.get(value, []):
            candidates.setdefault(target, []).append(("pattern", chain))

        if not candidates:
            if value in llm_rejection_by_value:
                matches.append(
                    ValueMatch(
                        source_value=value,
                        target_value=None,
                        confidence=Confidence.NONE,
                        rule="value_pairing.llm_rejected",
                        evidence=llm_rejection_by_value[value],
                        row_count=row_count,
                    )
                )
            else:
                matches.append(
                    ValueMatch(
                        source_value=value,
                        target_value=None,
                        confidence=Confidence.NONE,
                        rule="value_pairing.unpaired",
                        evidence=(
                            "No identity match, library match, or LLM-proposed transform "
                            "reproduced a target value."
                        ),
                        row_count=row_count,
                    )
                )
            continue

        matches.extend(
            _resolve_candidates(
                value=value,
                row_count=row_count,
                candidates=candidates,
                source_series=source_series,
                target_series=target_series,
                source_dates=source_dates,
                target_dates=target_dates,
                source_connector=source_connector,
                target_connector=target_connector,
                source_field=source_field,
                target_field=target_field,
                actor=actor,
                library_pairs=library_pairs,
                graph_run_id=graph_run_id,
            )
        )

    return matches


def pair_values_deterministic_only(
    *,
    source_field: str,
    target_field: str,
    source_series: pd.Series,
    target_series: pd.Series,
    source_connector: str,
    target_connector: str,
    source_dates: pd.Series | None = None,
    target_dates: pd.Series | None = None,
    actor: str = "system",
) -> ValueMapping:
    """Resolve every distinct ``source_field`` value using ONLY library lookup
    + identity match — never an LLM call. Used by the live recipe-editing
    pre-pass (see ``routes.live_pairing``) so editing a recipe step never
    triggers an LLM run; only an explicit "Run AI-mapping" does that (via
    :func:`pair_values`). Same resolution machinery as :func:`pair_values`
    (:func:`_assemble_and_resolve`/:func:`_resolve_candidates`), just with no
    LLM-derived or pattern-reused candidates ever in the mix.
    """
    source_counts = distinct_values(source_series)
    target_values = set(distinct_values(target_series))

    library_pairs = value_pair_store.lookup_pairs(
        source_connector=source_connector,
        target_connector=target_connector,
        source_field=source_field,
        target_field=target_field,
    )
    identity_candidate, _residual_source, _residual_target = identity_prepass(
        set(source_counts), target_values
    )

    matches = _assemble_and_resolve(
        unresolved=dict(source_counts),
        library_pairs=library_pairs,
        identity_candidate=identity_candidate,
        llm_result_by_value={},
        pattern_candidates={},
        llm_rejection_by_value={},
        source_series=source_series,
        target_series=target_series,
        source_dates=source_dates,
        target_dates=target_dates,
        source_connector=source_connector,
        target_connector=target_connector,
        source_field=source_field,
        target_field=target_field,
        actor=actor,
    )
    return ValueMapping(source_field=source_field, target_field=target_field, matches=matches)


def _pair_batch(
    *,
    source_counts: dict[str, int],
    target_values: set[str],
    source_field: str,
    target_field: str,
    source_series: pd.Series,
    target_series: pd.Series,
    source_connector: str,
    target_connector: str,
    mapping_sheet_context: Any,
    source_dates: pd.Series | None,
    target_dates: pd.Series | None,
    actor: str,
    batch_label: str,
    graph_run_id: str | None = None,
) -> tuple[list[ValueMatch], bool]:
    """One batch's worth of steps 0-4 (library, identity, LLM proposal +
    verification, pattern reuse, resolve) — everything :func:`pair_values`
    used to do in one dataset-wide pass, now scoped to ``source_counts`` (this
    batch's own distinct source values).

    ``target_values``/``target_series``/``target_dates`` scope is
    CALLER-DEPENDENT, not fixed by this function:

    - :func:`pair_values` (year-window batching, Manual mode and any caller
      that still wants dataset-wide target matching) always passes the FULL,
      unsliced target — see ``value_pairing.batching``'s module docstring on
      why that caller never slices the target side by date.
    - The Auto-mode streaming batch orchestrator
      (``auto_pipeline.nodes.run_batches``) passes THIS BATCH's own
      date-windowed target data instead — safe there specifically because
      date is a confirmed, reliable part of the business key, so both sides
      are windowed together by the same date-union batch and nothing can
      legitimately match outside it.

    Returns ``(matches, all_failed)`` — ``all_failed`` is True only when this
    batch had real residual LLM work and every configured provider failed it
    even after :data:`MAX_BATCH_LLM_RETRIES` retries.
    """
    unresolved: dict[str, int] = dict(source_counts)

    # Step 0: library-first lookup — queried FRESH for every batch, so a
    # pairing an EARLIER batch just persisted (see _finalize_single/
    # value_pair_store.propose) is already visible here, no extra plumbing
    # needed. Still recorded as a CANDIDATE, not popped and auto-accepted
    # (see module docstring).
    library_pairs = value_pair_store.lookup_pairs(
        source_connector=source_connector,
        target_connector=target_connector,
        source_field=source_field,
        target_field=target_field,
        graph_run_id=graph_run_id,
    )

    # Step 1: identity is a CANDIDATE, not an auto-accept (see module docstring).
    identity_candidate, _residual_source, _residual_target = identity_prepass(
        set(unresolved), target_values
    )

    # Step 2: Transformation Discovery (LLM), scoped to this batch's residual
    # source values only — the whole point of batching (smaller payload,
    # independently retryable). ``candidate_target`` still sees the complete
    # target-value universe as context, same as an unbatched call today.
    llm_candidates_source = sorted(v for v in unresolved if v not in library_pairs)
    confirmed_chains: dict[tuple, dict[str, Any]] = {}
    llm_result_by_value: dict[str, dict[str, Any]] = {}
    llm_rejection_by_value: dict[str, str] = {}

    proposed, all_failed = _propose_llm_chains_with_retry(
        candidate_source=llm_candidates_source,
        candidate_target=sorted(target_values),
        exact_matches=identity_candidate,
        mapping_sheet_context=mapping_sheet_context,
        batch_label=batch_label,
    )

    for candidate in proposed:
        value = candidate["source_value"]
        if value not in unresolved or value in llm_result_by_value:
            continue  # not a real residual value, or a duplicate proposal for it

        chain = candidate["ops"]
        claimed_target = candidate["target_value"]
        if claimed_target == value:
            # The LLM must never return an exact match — that's exclusively
            # the deterministic identity pre-pass's job. Drop it outright,
            # regardless of what the model claims (never trusted outright).
            continue
        # Some transforms are inherently one-directional (e.g. stripping
        # zero-padding only ever removes digits) — either side of the claim
        # can be the one that actually needs the transform applied, so both
        # directions are tried before rejecting.
        ok, direction = verify_chain_bidirectional(chain, source_field, value, claimed_target)

        if ok and claimed_target in target_values:
            confirmed_chains[_chain_key(chain)] = {"chain": chain, "direction": direction}
            llm_result_by_value[value] = {"target": claimed_target, "chain": chain, "direction": direction}
        elif not ok:
            passed, produced = verify_chain(chain, source_field, value)
            if not passed:
                llm_rejection_by_value[value] = (
                    f"LLM proposed {_format_chain(chain)} for {value!r}, "
                    f"but the operation chain failed: {produced} — rejected."
                )
            else:
                llm_rejection_by_value[value] = (
                    f"LLM proposed {_format_chain(chain)} claiming {value!r} -> {claimed_target!r}, "
                    f"but it produced {produced!r} in either direction — rejected."
                )
        else:
            llm_rejection_by_value[value] = (
                f"LLM claimed {value!r} -> {claimed_target!r} via {_format_chain(chain)} "
                f"(reproduced exactly), but {claimed_target!r} is not a real target value — rejected."
            )

    # Step 3: mechanically reapply every chain confirmed THIS BATCH — whether
    # it came from this value's own LLM proposal or one proposed for a
    # DIFFERENT value in the SAME batch — to every still-unresolved value in
    # the batch, no extra LLM call. This is what lets a value the LLM didn't
    # itself address (e.g. "7000", when only "5001" was explicitly proposed)
    # still pick up the same real transform. A chain confirmed in the
    # "reverse" direction (it reduces the TARGET down to the source, e.g.
    # stripping the target's zero-padding) is reused the same way: applied to
    # each candidate target and checked against the unresolved source value,
    # not the other way around.
    pattern_candidates: dict[str, list[tuple[str, _Chain]]] = {}
    reverse_lookup_cache: dict[tuple, dict[str, str]] = {}

    def _reverse_lookup(key: tuple, chain: _Chain) -> dict[str, str]:
        if key not in reverse_lookup_cache:
            lookup: dict[str, str] = {}
            for target in target_values:
                ok, produced = verify_chain(chain, source_field, target)
                if ok:
                    lookup.setdefault(produced, target)
            reverse_lookup_cache[key] = lookup
        return reverse_lookup_cache[key]

    for value in unresolved:
        own_key = _chain_key(llm_result_by_value[value]["chain"]) if value in llm_result_by_value else None
        for key, info in confirmed_chains.items():
            if key == own_key:
                continue  # already represented directly below
            chain = info["chain"]
            if info["direction"] == "reverse":
                target = _reverse_lookup(key, chain).get(value)
                if target is not None:
                    pattern_candidates.setdefault(value, []).append((target, chain))
            else:
                ok, produced = verify_chain(chain, source_field, value)
                if ok and produced in target_values:
                    pattern_candidates.setdefault(value, []).append((produced, chain))

    # Step 4: assemble every distinct candidate target per value and resolve
    # (shared with pair_values_deterministic_only — see _assemble_and_resolve).
    # source_series/target_series/dates passed through UNSLICED — corroboration
    # must see the whole dataset even for a value this batch happens to own.
    matches = _assemble_and_resolve(
        unresolved=unresolved,
        library_pairs=library_pairs,
        identity_candidate=identity_candidate,
        llm_result_by_value=llm_result_by_value,
        pattern_candidates=pattern_candidates,
        llm_rejection_by_value=llm_rejection_by_value,
        source_series=source_series,
        target_series=target_series,
        source_dates=source_dates,
        target_dates=target_dates,
        source_connector=source_connector,
        target_connector=target_connector,
        source_field=source_field,
        target_field=target_field,
        actor=actor,
        graph_run_id=graph_run_id,
    )
    return matches, all_failed


def _is_real_resolution(rule: str) -> bool:
    """False only for a same-batch-or-later restatement of an already-stored
    library pairing — i.e. a later batch re-encountering a recurring value
    that an EARLIER batch (or a prior run entirely) already resolved and
    persisted. Used by :func:`_merge_batch_matches` to prefer whichever
    instance carries the richer, original evidence."""
    return rule != "value_pairing.library_reused"


def _merge_batch_matches(all_batch_matches: list[list[ValueMatch]]) -> list[ValueMatch]:
    """Combine every batch's matches into ValueMapping.matches' final shape.

    A source value's records can legitimately span more than one batch (see
    ``value_pairing.batching``), so the SAME value can be independently
    resolved by more than one batch — the later one(s) via a cheap library
    hit (see module docstring). Deduped here by (source_value, target_value)
    so the final list never repeats a row purely because a later batch
    re-discovered it; row_count is summed across every batch the pairing
    appeared in. A value resolved in ANY batch is never ALSO reported
    unpaired just because a DIFFERENT batch's LLM call didn't happen to
    address it that time.
    """
    resolved: dict[tuple[str, str], ValueMatch] = {}
    unresolved: dict[str, ValueMatch] = {}

    for batch_matches in all_batch_matches:
        for m in batch_matches:
            if m.target_value is None:
                existing = unresolved.get(m.source_value)
                unresolved[m.source_value] = (
                    m if existing is None
                    else existing.model_copy(update={"row_count": existing.row_count + m.row_count})
                )
                continue

            key = (m.source_value, m.target_value)
            existing = resolved.get(key)
            if existing is None:
                resolved[key] = m
                continue
            keep_new = _is_real_resolution(m.rule) and not _is_real_resolution(existing.rule)
            winner = m if keep_new else existing
            resolved[key] = winner.model_copy(
                update={"row_count": existing.row_count + m.row_count}
            )

    resolved_source_values = {sv for sv, _tv in resolved}
    for source_value in resolved_source_values:
        unresolved.pop(source_value, None)

    return list(resolved.values()) + list(unresolved.values())


def pair_values(
    *,
    source_field: str,
    target_field: str,
    source_series: pd.Series,
    target_series: pd.Series,
    source_connector: str,
    target_connector: str,
    mapping_sheet_context: Any = None,
    source_dates: pd.Series | None = None,
    target_dates: pd.Series | None = None,
    actor: str = "system",
    max_dates_per_batch: int | None = None,
    raise_on_batch_failure: bool = False,
    on_batch: Any = None,
    start_batch_index: int = 0,
    resume_matches: list[ValueMatch] | None = None,
) -> ValueMapping:
    """Resolve every distinct ``source_field`` value to a ``target_field`` value.

    Partitions BOTH sides into ONE shared, date-aligned batch plan (see
    ``value_pairing.batching.build_batches`` — the same distinct-date-union
    algorithm the Auto pipeline's row-level extraction uses; a source/target
    record dated the same calendar day always lands in the same batch;
    ``max_dates_per_batch`` overrides ``batching.DEFAULT_MAX_DATES_PER_BATCH``
    when given) and runs library lookup -> identity -> LLM proposal
    (mandatorily verified) -> pattern reuse -> resolve (see
    :func:`_pair_batch`) once per batch, oldest first, merging every batch's
    matches at the end (see :func:`_merge_batch_matches`). The library is
    re-queried fresh every batch, so a pairing an earlier batch just persisted
    is reused (no LLM call) by a later batch that re-encounters the same
    value — this is what makes batching never cost a redundant LLM call for a
    value whose records span more than one batch.

    A stored library pairing is trusted immediately but is still only ONE
    candidate among however many a value turns out to have this run — it
    never suppresses a genuinely competing candidate (e.g. a coincidental
    identity match) the way an eager pop-and-return would.

    ``source_dates``/``target_dates`` are optional aligned date columns (same
    index as ``source_series``/``target_series``). Both ALSO drive batch
    partitioning (see ``value_pairing.batching``'s module docstring); both are
    used, unsliced, for the per-candidate corroboration signal. When neither
    is given, batching degrades to a single pass over everything (today's
    unbatched behavior) — a missing date column never blocks pairing.

    ``raise_on_batch_failure`` (default False, Manual mode's contract): when
    True, a batch whose LLM calls fail on every configured provider even
    after retrying raises :class:`ValuePairingUnavailable` immediately rather
    than degrading that batch's residual to unpaired — Auto mode has no human
    checkpoint to catch a silently-degraded run the way Manual mode's review
    step would, so it opts into this.

    ``on_batch``, if given, is called after each batch resolves with a
    :class:`~value_pairing.batching.BatchProgress` and that batch's own
    ``list[ValueMatch]`` — the hook Auto mode uses to surface live "batch N of
    M (label)" progress AND to persist a resumable per-batch checkpoint (see
    ``auto_pipeline.nodes._make_batch_progress_cb``).

    ``start_batch_index``/``resume_matches`` resume a PRIOR call that raised
    :class:`ValuePairingUnavailable` partway through: batches before
    ``start_batch_index`` are skipped entirely (never re-run — they already
    resolved and their matches were reported via ``on_batch`` before the
    prior call failed), and ``resume_matches`` (that prior call's already-
    resolved matches, gathered by the caller from its own checkpoint) are
    merged in as if they were produced by this call's own batch 0, so the
    returned ``ValueMapping`` covers every batch, not only the ones actually
    re-run this call.
    """
    target_values = set(distinct_values(target_series))
    batches = build_batches(
        source_series=source_series,
        target_series=target_series,
        source_dates=source_dates,
        target_dates=target_dates,
        max_dates_per_batch=max_dates_per_batch or DEFAULT_MAX_DATES_PER_BATCH,
    )
    # Display-only: which distinct target values share each batch's date
    # window. Never used for matching — see batching.py's module docstring.
    target_candidates_by_label = {
        label: len(distinct_values(target_series[tmask])) for label, _smask, tmask in batches
    }

    all_batch_matches: list[list[ValueMatch]] = [list(resume_matches)] if resume_matches else []
    for index, (label, smask, _tmask) in enumerate(batches):
        if index < start_batch_index:
            continue  # already resolved by a prior (failed) call — see resume_matches above
        batch_source_series = source_series[smask]
        source_counts = distinct_values(batch_source_series)
        batch_matches: list[ValueMatch] = []
        if source_counts:
            batch_matches, all_failed = _pair_batch(
                source_counts=source_counts,
                target_values=target_values,
                source_field=source_field,
                target_field=target_field,
                source_series=source_series,
                target_series=target_series,
                source_connector=source_connector,
                target_connector=target_connector,
                mapping_sheet_context=mapping_sheet_context,
                source_dates=source_dates,
                target_dates=target_dates,
                actor=actor,
                batch_label=label,
            )
            if all_failed and raise_on_batch_failure:
                raise ValuePairingUnavailable(
                    f"All configured AI providers are unavailable for value-pairing on "
                    f"{source_field!r} -> {target_field!r} (batch {label!r})."
                )
            all_batch_matches.append(batch_matches)

        if on_batch is not None:
            on_batch(
                BatchProgress(
                    field_pair=f"{source_field} -> {target_field}",
                    batch_index=index,
                    batch_count=len(batches),
                    batch_label=label,
                    target_candidate_count=target_candidates_by_label.get(label),
                ),
                batch_matches,
            )

    matches = _merge_batch_matches(all_batch_matches)
    return ValueMapping(source_field=source_field, target_field=target_field, matches=matches)
