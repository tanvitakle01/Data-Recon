"""Reusable attribute (column→column) mapping — the Library store's model.

A row here is a FIELD mapping (source column → target column) that drove a
completed reconciliation run, stored so the identical source+target column set
reappearing is answered from the library instead of the LLM. This is field
mapping only — never value mapping (that stays the deterministic matcher's job).

Pattern B: the columns you filter on (connectors, comparison type, the two
canonical column-set keys) are real typed columns; the variable payload
(``mappings``) and any future/artifact-specific fields (``details``) live in
JSON. A sibling artifact store (e.g. value_mappings) would be a NEW table of
this same shape — copy these conventions, don't generalize prematurely.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MappingProvenance(str, Enum):
    """Where a stored/served mapping came from (shown on the mapping card)."""

    LIBRARY = "library"              # reused from this store ("Generated via Vector Library")
    AZURE_FOUNDRY = "azure_foundry"  # inferred by Azure AI Foundry
    MANUAL = "manual"                # hand-edited / hand-added row
    # Legacy values kept only so MappingProvenance(row["provenance"]) can still
    # deserialize rows persisted before the LLM layer became Azure-AI-Foundry-only.
    GROQ = "groq"
    OPENAI = "openai"


class AttributePair(BaseModel):
    """One column→column pairing inside a stored mapping.

    ``extra="ignore"`` so a frontend ``display`` row (which also carries
    ``logical``/``provenance``) can be fed in without a validation error.
    """

    model_config = ConfigDict(extra="ignore")

    source_col: str
    target_col: str
    role: str = ""      # "key" | "compare" (matched loosely by /key/i downstream)
    reason: str = ""


class AttributeMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    # ── indexed key columns (grow to BW/Datasphere with zero schema change) ──
    source_connector: str
    target_connector: str
    comparison_type: str
    source_columns_key: str  # canonical_column_key(source columns)
    target_columns_key: str  # canonical_column_key(target columns)
    # ── payload + provenance ────────────────────────────────────────────────
    mappings: list[AttributePair] = Field(default_factory=list)
    provenance: MappingProvenance = MappingProvenance.LIBRARY
    confidence: float | None = None
    added_by: str = "system"
    added_on: datetime = Field(default_factory=_utcnow)
    last_used_on: datetime | None = None
    validated_by_run_id: str | None = None
    version: int = 1
    # Artifact-specific / future fields (e.g. the raw column universe used for
    # the key, for debugging a mismatch). Never used for lookup.
    details: dict[str, Any] = Field(default_factory=dict)
