"""Deterministic value-level mapping (the "(B) VALUE MAPPING" concern).

A ``ValueMapping`` is the auditable record of how every distinct source value
of one mapped Key field (e.g. every distinct ``Material``) was resolved
against the target's distinct values (e.g. every distinct ``PRDID``) by the
deterministic tiered matcher in ``recon_engine.matching``. Never guessed, never
touches an LLM — every entry carries a reproducible rule id and a
human-readable evidence string.

This is deliberately a *contract-level* fact, separate from the executable
``ContractOperation``. ``engine.executor`` is the only thing that turns it
into an actual ``value_mapping`` operation at build time, applying the
confidence policy below.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Confidence(str, Enum):
    """Tiers a deterministic match can land on.

    ``OUT_OF_SCOPE`` isn't a confidence level at all — it means the source
    value was excluded from matching entirely (e.g. a raw-material
    MaterialGroup that IBP doesn't track as a finished-goods product), so it
    must never be reported as a coverage gap the way ``NONE`` is.
    """

    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    NONE = "none"
    OUT_OF_SCOPE = "out_of_scope"


# Confidence tiers the engine auto-applies to the Shadow_Source without human
# sign-off (approved by the user's stated policy: VERY_HIGH + HIGH).
AUTO_APPLY_CONFIDENCE: frozenset[Confidence] = frozenset({Confidence.VERY_HIGH, Confidence.HIGH})
# Every other tier: held out of the Shadow_Source entirely (never silently
# kept, never silently transformed, never rejoined on an unresolved value).
# MEDIUM is held out same as NONE/OUT_OF_SCOPE — there is no review workflow;
# a MEDIUM match is simply not confident enough to apply.
HOLD_OUT_CONFIDENCE: frozenset[Confidence] = frozenset(
    {Confidence.MEDIUM, Confidence.NONE, Confidence.OUT_OF_SCOPE}
)


class ValueMatch(BaseModel):
    """One resolved (or unresolved) source value.

    ``target_value`` is ``None`` exactly when ``confidence`` is ``NONE`` or
    ``OUT_OF_SCOPE`` — there was nothing to map to (or nothing was attempted).
    """

    model_config = ConfigDict(extra="forbid")

    source_value: str
    target_value: str | None = None
    confidence: Confidence
    rule: str = Field(..., description="Stable rule id, e.g. 'product.rule2_exact_id'.")
    evidence: str = Field(..., description="Human-readable reason a person can audit.")
    row_count: int = Field(0, description="How many source rows carry this value.")
    # Populated only for an ambiguous match (e.g. a description bridge landing on
    # more than one PRDID): every candidate target value, so a human reviewer can
    # pick one. When set, `target_value` is left `None` — nothing is guessed.
    # Confidence is always MEDIUM here, so the executor never auto-applies it
    # regardless of this field; it exists purely to inform the reviewer.
    candidates: list[str] | None = None


class ValueMapping(BaseModel):
    """The full deterministic mapping for one Key field pair (e.g. Material -> PRDID).

    Carried on the contract (``ContractBody.value_mappings``) as an auditable
    fact, separate from execution. See ``executable_mapping`` below and
    ``engine.executor`` for how it becomes a real transform.
    """

    model_config = ConfigDict(extra="forbid")

    source_field: str
    target_field: str
    matches: list[ValueMatch] = Field(default_factory=list)

    def executable_mapping(self) -> dict[str, str]:
        """VERY_HIGH/HIGH matches only — what the engine actually applies."""
        return {
            m.source_value: m.target_value
            for m in self.matches
            if m.confidence in AUTO_APPLY_CONFIDENCE and m.target_value is not None
        }

    def held_out_matches(self) -> list[ValueMatch]:
        """MEDIUM/NONE/OUT_OF_SCOPE matches — rows the engine holds out of the shadow."""
        return [m for m in self.matches if m.confidence in HOLD_OUT_CONFIDENCE]
