"""Persisted value-pairing library (the value_pair_library store).

A ``ValuePair`` is one ``source_value -> target_value`` pairing for a Key field
pair (e.g. Material -> PRDID), proposed by the LLM-pairing pipeline
(``recon_engine.value_pairing``) and deterministically verified — the claimed
``op``/``params`` were re-executed against the real ``source_value`` and
reproduced ``target_value`` exactly — before it is ever written here. Once
stored, a pair is immediately usable by future runs via the pipeline's
library-first lookup — no separate review step.

This is deliberately separate from ``models.value_mapping.ValueMapping`` — that
is the per-run, contract-level fact the executor consumes (unaffected by this
model). This one is the durable, cross-run reuse store, following the same
Pattern-B convention as ``models.attribute_mapping.AttributeMapping``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ValuePair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    # ── indexed key columns ──────────────────────────────────────────────────
    source_connector: str
    target_connector: str
    source_field: str
    target_field: str
    source_value: str
    # ── payload ──────────────────────────────────────────────────────────────
    target_value: str
    # Ordered sequence of allow-listed op+params steps whose FINAL output
    # reproduces target_value from source_value (verified — see
    # value_pairing.verify.verify_chain). A single-step transform is simply a
    # one-element list; never a bare op/params pair, so a one-op and a
    # multi-op pairing are stored identically.
    ops: list[dict[str, Any]] = Field(default_factory=list)
    # Sample row refs, the LLM's rationale, and the verification detail —
    # everything needed to audit the claim without re-deriving it.
    evidence: dict[str, Any] = Field(default_factory=dict)
    added_by: str = "system"
    added_on: datetime = Field(default_factory=_utcnow)
    version: int = 1
