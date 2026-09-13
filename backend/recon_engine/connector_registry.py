"""Connector registry — Stage-1 stub.

Stage-1 is file-upload only: there are no live-fetch connectors (SAP S/4HANA,
SAP IBP) anymore, so this registry is permanently empty. It keeps the same
public surface the mapping-sheet identification flow (``sheet_identifier.py``,
``routes/contracts.py``, ``routes/entity_join.py``) already calls, so that
code's existing "no connector configured for this kind" degrade paths handle
Stage-1 without any further branching: the LLM's connector guess is always
flagged as ``unidentified`` (never coerced), and entity/join catalogs always
come back empty with a warning — exactly the behavior those call sites already
have for an unconfigured/unreachable connector.
"""

from __future__ import annotations

from dataclasses import dataclass

# Roles a connector may occupy in a reconciliation. Kept as bare strings to
# match the existing free-text source_type/target_type convention.
SOURCE = "source"
TARGET = "target"


@dataclass(frozen=True)
class ConnectorSpec:
    """Static metadata for a connector that exists in code. Never populated in
    Stage-1 — kept only so type hints elsewhere still resolve."""

    kind: str
    role: str
    label: str
    has_planning_areas: bool = False


def get_spec(kind: str | None) -> ConnectorSpec | None:
    return None


def is_registered_kind(kind: str | None) -> bool:
    return False


def get_connectors() -> list[dict]:
    return []


def get_configured_connectors(role: str | None = None) -> list[dict]:
    return []


def configured_kinds() -> set[str]:
    return set()
