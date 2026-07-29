"""Identity pre-pass — pipeline step 2. Exact string matches, no LLM call, free."""

from __future__ import annotations


def identity_prepass(
    source_values: set[str], target_values: set[str]
) -> tuple[dict[str, str], set[str], set[str]]:
    """Exact-match pairs, plus the residual unmatched values on each side.

    Only values that fail this pre-pass proceed to LLM pairing.
    """
    matched = source_values & target_values
    pairs = {value: value for value in matched}
    residual_source = source_values - matched
    residual_target = target_values - matched
    return pairs, residual_source, residual_target
