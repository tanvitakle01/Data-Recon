"""Structured business rules — the machine-readable replacement for the
free-text "Additional Rules / Instructions" field.

A ``BusinessRule`` names a field (as the user understands it — resolved
against the real schema by the compiler, never assumed here) and a
plain-language instruction. Three categories group rules by intent so a
compiler knows what kind of contract element the instruction is likely to
produce:

    transformation_rules -> operations (transform kind)
    matching_rules        -> compare_fields (match_type / tolerance / equivalence)
    filter_rules          -> operations (filter kind)

Nothing here assumes a specific system, table, or field name — this module
only defines and normalises the shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BusinessRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    instruction: str


class BusinessRules(BaseModel):
    """The structured replacement for a single free-text ``rules`` string."""

    model_config = ConfigDict(extra="forbid")

    transformation_rules: list[BusinessRule] = Field(default_factory=list)
    matching_rules: list[BusinessRule] = Field(default_factory=list)
    filter_rules: list[BusinessRule] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.transformation_rules or self.matching_rules or self.filter_rules)

    def to_prompt_text(self) -> str:
        """Render as a deterministic, human-readable text block.

        Used only where a single string is still required (audit notes, the
        script-transformation generator's free-text prompt slot) — never a
        substitute for passing the structured JSON directly where a consumer
        can take it.
        """
        lines: list[str] = []
        for label, rules in (
            ("Data Transformation", self.transformation_rules),
            ("Matching", self.matching_rules),
            ("Filter", self.filter_rules),
        ):
            for rule in rules:
                lines.append(f"[{label}] {rule.field}: {rule.instruction}")
        return "\n".join(lines)


def normalize_business_rules(raw: BusinessRules | dict | None) -> BusinessRules:
    """Trim whitespace and drop rows missing a field or instruction.

    Rule ordering within each category is preserved. Accepts a
    ``BusinessRules`` instance, a raw dict (e.g. straight off a request
    body), or ``None`` (treated as empty).
    """
    parsed = raw if isinstance(raw, BusinessRules) else BusinessRules.model_validate(raw or {})

    def _clean(rules: list[BusinessRule]) -> list[BusinessRule]:
        cleaned: list[BusinessRule] = []
        for rule in rules:
            field = (rule.field or "").strip()
            instruction = (rule.instruction or "").strip()
            if field and instruction:
                cleaned.append(BusinessRule(field=field, instruction=instruction))
        return cleaned

    return BusinessRules(
        transformation_rules=_clean(parsed.transformation_rules),
        matching_rules=_clean(parsed.matching_rules),
        filter_rules=_clean(parsed.filter_rules),
    )
