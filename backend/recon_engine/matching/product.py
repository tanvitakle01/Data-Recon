"""Deterministic tiered matcher: SAP ``Material`` -> IBP ``PRDID``.

Pure function of the real column values (+ optional user overrides) — no I/O,
no hidden state, never touches an LLM. Every distinct source value is checked
against the rules below IN ORDER and stops at the first that fires; every
result carries a reproducible rule id and a human-readable evidence string.

Rule order (approved design; Rule 4's docstring notes what the real data
looked like at design time so this stays honest as data changes):

    0. MaterialGroup in {RM, PCB, ASY}     -> OUT_OF_SCOPE (not a gap)
    1. Material == PRDID AND group aligns  -> VERY_HIGH
    2. Material == PRDID only              -> HIGH
    3. normalized identity (case/separator variance) -> HIGH
    4. alternate id (PRDIDDEM/SPRDID)       -> HIGH, ONLY IF the target data
       actually populates either column for at least one row. On the data seen
       during design (Phase 1 confirmation), PRDIDDEM and SPRDID were 0%
       filled — this rule evaluated to unreachable for every value there, and
       skips cleanly rather than being faked.
    5. description bridge: this Material's associated SalesOrderItemText
       (order-line free text, NOT the Material code itself) matches a known
       IBP PRODDESC -> MEDIUM. A Material can carry more than one distinct
       order-line text; every one is checked, and every distinct PRDID reached
       across them is a candidate. Exactly one candidate -> that PRDID is
       suggested as `target_value` (still MEDIUM, still held out — never
       auto-applied). More than one -> ambiguous: `target_value` is left
       `None` and every candidate is recorded on `ValueMatch.candidates` for
       auditability; nothing is guessed.
    6. no match                             -> NONE
"""

from __future__ import annotations

import re

import pandas as pd

from backend.recon_engine.models.value_mapping import Confidence, ValueMapping, ValueMatch

_OUT_OF_SCOPE_GROUPS = frozenset({"RM", "PCB", "ASY"})
_FINISHED_GOODS_GROUPS = frozenset({"FG"})


def _normalize_identity(value: str) -> str:
    """Case/separator-insensitive identity: upper-case, strip non-alphanumerics."""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _normalize_text(value: str) -> str:
    """Case/whitespace-insensitive text match for the description bridge.

    Deliberately weaker than ``_normalize_identity``: these are free-text
    descriptions, not codes, so only case and surrounding whitespace are
    normalized — collapsing internal spaces/punctuation would merge distinct
    phrases (e.g. "finished good" and "finishedgood") that happen to share
    consonants.
    """
    return value.strip().lower()


def _value_groups(values: pd.Series, groups: pd.Series | None) -> dict[str, set[str]]:
    """distinct non-null value -> set of non-blank group-column values seen with it."""
    out: dict[str, set[str]] = {}
    if groups is None:
        for v in values.dropna().astype(str):
            out.setdefault(v, set())
        return out
    paired = pd.DataFrame({"v": values.astype(str), "g": groups}).dropna(subset=["v"])
    for v, sub in paired.groupby("v"):
        out[v] = set(sub["g"].dropna().astype(str)) - {""}
    return out


def match_products(
    *,
    source_material: pd.Series,
    source_material_group: pd.Series | None,
    target_prdid: pd.Series,
    target_prodgroup: pd.Series | None = None,
    target_descriptions: list[pd.Series] | None = None,
    target_alt_ids: list[pd.Series] | None = None,
    source_order_item_text: pd.Series | None = None,
    overrides: dict[str, str] | None = None,
) -> ValueMapping:
    """Match every distinct SAP ``Material`` value to an IBP ``PRDID`` value.

    ``source_order_item_text`` (SAP ``SalesOrderItemText``, aligned 1:1 with
    ``source_material`` — same index) feeds Rule 5's description bridge; a
    Material with no associated text, or when this is omitted entirely, simply
    can't reach Rule 5 and falls through to Rule 6 like any other unreachable
    rule (see Rule 4's precedent in the module docstring).

    ``overrides`` (source_value -> target_value) short-circuits every rule for
    that value and is recorded at VERY_HIGH with rule ``"product.override"`` —
    a human correction always wins over the deterministic rules.
    """
    overrides = overrides or {}

    material_counts = source_material.dropna().astype(str)
    material_counts = material_counts[material_counts.str.strip() != ""].value_counts()
    material_groups = _value_groups(source_material, source_material_group)
    order_texts_by_material = _value_groups(source_material, source_order_item_text)

    prdid_set = set(target_prdid.dropna().astype(str)) - {""}
    prdid_norm = {_normalize_identity(p): p for p in prdid_set}
    prodgroup_by_prdid = _value_groups(target_prdid, target_prodgroup)

    # Rule 4 reachability check — see module docstring. ``target_alt_ids`` is a
    # tier-ranked list of alternate-id columns (PRDIDDEM, SPRDID, ZPECID, …);
    # each value keeps the column it came from so evidence can cite it. First
    # column (highest tier) wins on collision.
    alt_id_by_value: dict[str, tuple[str, str]] = {}  # alt_value -> (prdid, field)
    for idx, alt_col in enumerate(target_alt_ids or []):
        if alt_col is None:
            continue
        label = str(alt_col.name) if alt_col.name is not None else f"ALT_ID_{idx}"
        paired = pd.DataFrame({"alt": alt_col.astype(str), "prdid": target_prdid.astype(str)})
        paired = paired[
            paired["alt"].notna() & (paired["alt"].str.strip() != "") & (paired["alt"].str.lower() != "none")
        ]
        for alt, prdid in zip(paired["alt"], paired["prdid"]):
            alt_id_by_value.setdefault(alt, (prdid, label))
    alt_id_reachable = bool(alt_id_by_value)

    # Rule 5: description -> {every PRDID seen with it} (never first-wins — an
    # ambiguous description must surface ALL candidates, not silently pick one).
    # ``target_descriptions`` is a tier-ranked list of description columns
    # (PRODDESC, PRODDESCDEM, SPRODDESC, …); their maps are unioned so a match
    # in any of them reaches the bridge.
    grouped: dict[str, set[str]] = {}
    for desc_col in (target_descriptions or []):
        if desc_col is None:
            continue
        paired = pd.DataFrame({"desc": desc_col.astype(str), "prdid": target_prdid.astype(str)})
        paired = paired[paired["desc"].notna() & (paired["desc"].str.strip() != "")]
        for desc, prdid in zip(paired["desc"], paired["prdid"]):
            grouped.setdefault(_normalize_text(desc), set()).add(prdid)
    desc_to_prdids: dict[str, list[str]] = {k: sorted(v) for k, v in grouped.items()}
    desc_bridge_reachable = source_order_item_text is not None and bool(desc_to_prdids)

    matches: list[ValueMatch] = []
    for material, row_count in material_counts.items():
        row_count = int(row_count)

        if material in overrides:
            matches.append(
                ValueMatch(
                    source_value=material,
                    target_value=overrides[material],
                    confidence=Confidence.VERY_HIGH,
                    rule="product.override",
                    evidence=f"User override: {material!r} -> {overrides[material]!r}.",
                    row_count=row_count,
                )
            )
            continue

        groups_here = material_groups.get(material, set())

        # Rule 0: scope filter, evaluated before any match attempt.
        out_of_scope_hit = groups_here & _OUT_OF_SCOPE_GROUPS
        if out_of_scope_hit:
            hit = sorted(out_of_scope_hit)[0]
            matches.append(
                ValueMatch(
                    source_value=material,
                    target_value=None,
                    confidence=Confidence.OUT_OF_SCOPE,
                    rule="product.rule0_group_out_of_scope",
                    evidence=(
                        f"MaterialGroup={hit!r} is outside IBP's finished-goods scope; "
                        "not reconciled, not counted as a gap."
                    ),
                    row_count=row_count,
                )
            )
            continue

        # Rules 1/2: exact Material == PRDID, split by group alignment.
        if material in prdid_set:
            target_groups = prodgroup_by_prdid.get(material, set())
            aligned = bool(groups_here & _FINISHED_GOODS_GROUPS) and bool(
                target_groups & _FINISHED_GOODS_GROUPS
            )
            if aligned:
                matches.append(
                    ValueMatch(
                        source_value=material,
                        target_value=material,
                        confidence=Confidence.VERY_HIGH,
                        rule="product.rule1_exact_id_group_aligned",
                        evidence=(
                            f"Exact match on Material/PRDID; MaterialGroup={sorted(groups_here)} "
                            f"aligns with PRODGROUP={sorted(target_groups)} (both FG)."
                        ),
                        row_count=row_count,
                    )
                )
            else:
                matches.append(
                    ValueMatch(
                        source_value=material,
                        target_value=material,
                        confidence=Confidence.HIGH,
                        rule="product.rule2_exact_id",
                        evidence=(
                            f"Exact match on Material/PRDID (MaterialGroup={sorted(groups_here) or ['?']}, "
                            f"PRODGROUP={sorted(target_groups) or ['?']} did not both confirm FG)."
                        ),
                        row_count=row_count,
                    )
                )
            continue

        # Rule 3: normalized identity (case/separator variance only).
        norm = _normalize_identity(material)
        normalized_hit = prdid_norm.get(norm)
        if normalized_hit is not None and normalized_hit != material:
            matches.append(
                ValueMatch(
                    source_value=material,
                    target_value=normalized_hit,
                    confidence=Confidence.HIGH,
                    rule="product.rule3_normalized_identity",
                    evidence=f"Normalized match: {material!r} ~ {normalized_hit!r} (case/separator variance only).",
                    row_count=row_count,
                )
            )
            continue

        # Rule 4: alternate id (PRDIDDEM/SPRDID/…) — only if reachable at all.
        if alt_id_reachable and material in alt_id_by_value:
            target_val, alt_field = alt_id_by_value[material]
            matches.append(
                ValueMatch(
                    source_value=material,
                    target_value=target_val,
                    confidence=Confidence.HIGH,
                    rule="product.rule4_alternate_id",
                    evidence=f"Matched via alternate id ({alt_field}) to PRDID {target_val!r}.",
                    row_count=row_count,
                )
            )
            continue

        # Rule 5: description bridge — this Material's associated
        # SalesOrderItemText value(s) matched against PRODDESC, not the
        # Material code itself. Every distinct candidate PRDID reached across
        # all of this material's texts is collected; one candidate resolves,
        # more than one is ambiguous (see module docstring).
        material_texts = order_texts_by_material.get(material, set())
        if desc_bridge_reachable and material_texts:
            candidate_prdids: set[str] = set()
            matched_texts: list[str] = []
            for text in sorted(material_texts):
                hit = desc_to_prdids.get(_normalize_text(text))
                if hit:
                    candidate_prdids.update(hit)
                    matched_texts.append(text)

            if len(candidate_prdids) == 1:
                target_val = next(iter(candidate_prdids))
                matches.append(
                    ValueMatch(
                        source_value=material,
                        target_value=target_val,
                        confidence=Confidence.MEDIUM,
                        rule="product.rule5_description_match",
                        evidence=(
                            f"SalesOrderItemText {matched_texts[0]!r} matches a PRODDESC "
                            f"mapped to PRDID {target_val!r}."
                        ),
                        row_count=row_count,
                    )
                )
                continue
            if len(candidate_prdids) > 1:
                candidates_sorted = sorted(candidate_prdids)
                matches.append(
                    ValueMatch(
                        source_value=material,
                        target_value=None,
                        confidence=Confidence.MEDIUM,
                        rule="product.rule5_description_match_ambiguous",
                        evidence=(
                            f"SalesOrderItemText {matched_texts!r} matches PRODDESC values "
                            f"mapped to multiple PRDIDs {candidates_sorted} — ambiguous, "
                            "a human must pick one."
                        ),
                        candidates=candidates_sorted,
                        row_count=row_count,
                    )
                )
                continue

        # Rule 6: no match.
        reason = "No PRDID matches this Material by any deterministic rule"
        unreachable_notes = []
        if not alt_id_reachable:
            unreachable_notes.append("rule 4/alternate-id: no alternate-id columns populated in this target data")
        if not desc_bridge_reachable:
            unreachable_notes.append("rule 5/description-bridge: no SalesOrderItemText supplied or no description data")
        if unreachable_notes:
            reason += " (unreachable rules: " + "; ".join(unreachable_notes) + ")"
        matches.append(
            ValueMatch(
                source_value=material,
                target_value=None,
                confidence=Confidence.NONE,
                rule="product.rule6_no_match",
                evidence=reason + ".",
                row_count=row_count,
            )
        )

    return ValueMapping(source_field="Material", target_field="PRDID", matches=matches)
