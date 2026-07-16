"""Deterministic tiered matcher: SAP ``ProductionPlant`` -> IBP ``LOCID``.

Pure function of the real column values (+ optional user overrides) — no I/O,
no hidden state, never touches an LLM. Stops at the first rule that fires.

Rule order (approved design):

    1. Plant == LOCID                          -> VERY_HIGH
    2. plant code embedded in LOCID or LOCNAME  -> HIGH (records which field
       the match came from). "Embedded" requires a genuine token boundary,
       not an incidental substring — see ``_embedded_match``. Real example
       this must still catch: plant ``"S101"`` embedded in LOCID
       ``"DCS101@S21400"`` (right after the "DC" organizational prefix, no
       separator) — so the boundary rule can't simply require a
       non-alphanumeric character on both sides; it only rejects an embedding
       that is itself a fragment of a *longer digit run* (e.g. plant ``"01"``
       "found" inside an unrelated ``"2010"``).
    3. no match                                 -> NONE
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.models.value_mapping import Confidence, ValueMapping, ValueMatch


def _embedded_match(code: str, haystack: str) -> bool:
    """True if ``code`` is embedded in ``haystack`` as a genuine token, not a
    fragment of a longer number.

    A plain ``code in haystack`` substring test would treat plant ``"01"`` as
    "found" inside an unrelated ``"2010"`` — a spurious hit purely because one
    number happens to contain another's digits. This additionally requires
    that wherever the match borders a digit *of its own* (at its first or last
    character), the adjacent haystack character isn't *also* a digit — that's
    the signature of being sliced out of a bigger number. Letter-adjacency is
    fine (that's how real IBP LOCIDs are built here: an org prefix like "DC"
    or "PL" directly followed by the plant code, e.g. "DCS101@S21400").
    """
    start = 0
    while True:
        idx = haystack.find(code, start)
        if idx == -1:
            return False
        left_ok = not (code[0].isdigit() and idx > 0 and haystack[idx - 1].isdigit())
        end = idx + len(code)
        right_ok = not (code[-1].isdigit() and end < len(haystack) and haystack[end].isdigit())
        if left_ok and right_ok:
            return True
        start = idx + 1


def _locid_for_name(locname: str, target_locid: pd.Series, target_locname: pd.Series) -> str | None:
    """Resolve a LOCNAME hit back to its LOCID — the field we actually map to."""
    paired = pd.DataFrame({"id": target_locid.astype(str), "name": target_locname.astype(str)})
    hit = paired[paired["name"] == locname]
    return str(hit["id"].iloc[0]) if not hit.empty else None


def match_locations(
    *,
    source_plant: pd.Series,
    target_locid: pd.Series,
    target_locname: pd.Series | None = None,
    overrides: dict[str, str] | None = None,
) -> ValueMapping:
    """Match every distinct SAP ``ProductionPlant`` value to an IBP ``LOCID`` value.

    ``overrides`` (source_value -> target_value) short-circuits every rule for
    that value and is recorded at VERY_HIGH with rule ``"location.override"``.
    """
    overrides = overrides or {}

    plant_counts = source_plant.dropna().astype(str)
    plant_counts = plant_counts[plant_counts.str.strip() != ""].value_counts()

    locid_list = sorted(set(target_locid.dropna().astype(str)) - {""})
    locname_list = (
        sorted(set(target_locname.dropna().astype(str)) - {""}) if target_locname is not None else []
    )
    locid_set = set(locid_list)

    matches: list[ValueMatch] = []
    for plant, row_count in plant_counts.items():
        row_count = int(row_count)

        if plant in overrides:
            matches.append(
                ValueMatch(
                    source_value=plant,
                    target_value=overrides[plant],
                    confidence=Confidence.VERY_HIGH,
                    rule="location.override",
                    evidence=f"User override: {plant!r} -> {overrides[plant]!r}.",
                    row_count=row_count,
                )
            )
            continue

        # Rule 1: exact match.
        if plant in locid_set:
            matches.append(
                ValueMatch(
                    source_value=plant,
                    target_value=plant,
                    confidence=Confidence.VERY_HIGH,
                    rule="location.rule1_exact_id",
                    evidence=f"Exact match on ProductionPlant/LOCID ({plant!r}).",
                    row_count=row_count,
                )
            )
            continue

        # Rule 2: plant code embedded in LOCID or LOCNAME (boundary-aware).
        embedded_in = next((loc for loc in locid_list if _embedded_match(plant, loc)), None)
        field = "LOCID"
        if embedded_in is None:
            embedded_in = next((loc for loc in locname_list if _embedded_match(plant, loc)), None)
            field = "LOCNAME"
        if embedded_in is not None:
            target_val = (
                embedded_in
                if field == "LOCID"
                else _locid_for_name(embedded_in, target_locid, target_locname)
            )
            if target_val is not None:
                matches.append(
                    ValueMatch(
                        source_value=plant,
                        target_value=target_val,
                        confidence=Confidence.HIGH,
                        rule="location.rule2_embedded_code",
                        evidence=f"Plant code {plant!r} embedded in {field} {embedded_in!r}.",
                        row_count=row_count,
                    )
                )
                continue

        # Rule 3: no match.
        matches.append(
            ValueMatch(
                source_value=plant,
                target_value=None,
                confidence=Confidence.NONE,
                rule="location.rule3_no_match",
                evidence="No LOCID/LOCNAME contains or equals this plant code.",
                row_count=row_count,
            )
        )

    return ValueMapping(source_field="ProductionPlant", target_field="LOCID", matches=matches)
