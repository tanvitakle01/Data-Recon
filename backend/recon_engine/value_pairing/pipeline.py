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
from backend.recon_engine.llm import build_llm_client
from backend.recon_engine.models.value_mapping import Confidence, ValueMapping, ValueMatch
from backend.recon_engine.storage import value_pair_store
from backend.recon_engine.value_pairing.corroborate import corroboration_overlap
from backend.recon_engine.value_pairing.extraction import distinct_values
from backend.recon_engine.value_pairing.identity import identity_prepass
from backend.recon_engine.value_pairing.prompt import build_messages, parse_candidates
from backend.recon_engine.value_pairing.verify import verify_chain, verify_chain_bidirectional

logger = logging.getLogger("recon.value_pairing")

_Chain = list[dict[str, Any]]


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
) -> ValueMapping:
    """Resolve every distinct ``source_field`` value to a ``target_field`` value.

    Step order: look up any stored library pairing (no LLM cost, no
    re-verification) -> build every value's full candidate set (that stored
    pairing, plus identity, plus reused chains, plus fresh LLM chains, each
    mandatorily verified) -> resolve a sole candidate cheaply, or accept every
    candidate when several compete for a value (see module docstring). A
    stored library pairing is trusted immediately but is still only ONE
    candidate among however many a value turns out to have this run — it
    never suppresses a genuinely competing candidate (e.g. a coincidental
    identity match) the way an eager pop-and-return would.
    ``source_dates``/``target_dates`` are optional aligned date columns (same
    index as ``source_series``/``target_series``) used only to compute the
    per-candidate corroboration signal; when omitted, corroboration always
    reports "no signal" but every verified candidate is still accepted.
    """
    source_counts = distinct_values(source_series)
    target_values = set(distinct_values(target_series))

    unresolved: dict[str, int] = dict(source_counts)

    # Step 0: library-first lookup. This exact pairing was already verified
    # and stored on a prior run, so it never costs an LLM call or a
    # re-verification — but it is recorded as a CANDIDATE, not popped and
    # auto-accepted here, so it can never silently outrank or hide a
    # genuinely competing candidate for the same value discovered below (see
    # module docstring: a value can legitimately carry more than one verified
    # candidate — a stored prior pairing is no exception to that rule).
    library_pairs = value_pair_store.lookup_pairs(
        source_connector=source_connector,
        target_connector=target_connector,
        source_field=source_field,
        target_field=target_field,
    )

    # Step 1: identity is a CANDIDATE, not an auto-accept (see module docstring).
    identity_candidate, _residual_source, _residual_target = identity_prepass(
        set(unresolved), target_values
    )

    # Step 2: Transformation Discovery (LLM). The LLM sees the COMPLETE
    # source-value list minus only values already stored in the library —
    # deliberately INCLUDING values that already have an identity (exact)
    # match, so it can identify a genuinely ADDITIONAL transform-based target
    # for them (both must coexist per the rules — see prompt.py). It must
    # never return the exact match itself; any candidate claiming target ==
    # source is dropped below regardless of what the model returns. Each
    # proposal is an ordered chain; verification applies the FULL chain and
    # checks only the final result.
    llm_candidates_source = sorted(v for v in unresolved if v not in library_pairs)
    confirmed_chains: dict[tuple, dict[str, Any]] = {}
    llm_result_by_value: dict[str, dict[str, Any]] = {}
    llm_rejection_by_value: dict[str, str] = {}

    for candidate in _propose_llm_chains(
        candidate_source=llm_candidates_source,
        candidate_target=sorted(target_values),
        exact_matches=identity_candidate,
        mapping_sheet_context=mapping_sheet_context,
    ):
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

    # Step 3: mechanically reapply every chain confirmed THIS RUN — whether it
    # came from this value's own LLM proposal or one proposed for a DIFFERENT
    # value — to every still-unresolved value, no extra LLM call. This is
    # what lets a value the LLM didn't itself address (e.g. "7000", when only
    # "5001" was explicitly proposed) still pick up the same real transform.
    # A chain confirmed in the "reverse" direction (it reduces the TARGET down
    # to the source, e.g. stripping the target's zero-padding) is reused the
    # same way: applied to each candidate target and checked against the
    # unresolved source value, not the other way around.
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
    )

    return ValueMapping(source_field=source_field, target_field=target_field, matches=matches)
