"""Auto/Chatbot-pipeline connector helpers for date-aligned streaming-batch
planning.

The core distinct-date-union batch-planning algorithm (``DateBatch``,
``plan_batches``) now lives in ``recon_engine.date_batch_planning`` — shared
with ``value_pairing.batching``, which uses the same algorithm to batch
Manual mode's value-pairing LLM calls. Re-exported here so every existing
import site in this package keeps working unchanged.

This module keeps only what's specific to the Auto pipeline: resolving a
connector client, locating which entity/field to pull a date column from, and
the cheap paginated single-column fetch used to build the date union BEFORE
any full extraction happens.
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from backend.API_conn.connectors.ibp_metadata_service import IBPMetadataService
from backend.API_conn.connectors.s4_metadata_service import S4MetadataService
from backend.recon_engine.date_batch_planning import (
    DEFAULT_MAX_DATES_PER_BATCH,
    DEFAULT_RECORD_THRESHOLD,
    DateBatch,
    plan_batches,
)

__all__ = [
    "DEFAULT_MAX_DATES_PER_BATCH",
    "DEFAULT_RECORD_THRESHOLD",
    "DateBatch",
    "plan_batches",
    "client_for",
    "entity_and_field_for_batch",
    "fetch_date_column",
]


class _ColumnFetcher(Protocol):
    def preview_column(
        self, entity_name: str, field: str, date_filter: tuple[Any, Any] | None = None
    ) -> pd.Series: ...


def client_for(kind: str):
    """Shared by ``nodes.py`` (batch planning/extraction) and
    ``data_fingerprint.py`` (suspend/resume staleness) — the one place a
    connector kind resolves to a fresh client instance."""
    if kind == "s4":
        return S4MetadataService()
    if kind == "ibp":
        return IBPMetadataService()
    raise RuntimeError(f"No connector client for kind {kind!r}.")


def entity_and_field_for_batch(spec: dict[str, Any], kind: str, date_field: str) -> tuple[str, str]:
    """Which entity to pull ``date_field`` from — for S4, the entity in the
    join spec (primary or one of the joins) that actually carries it; for
    IBP, the single entity. Shared by ``nodes.py`` and ``data_fingerprint.py``."""
    if kind == "ibp":
        return spec["entity"], date_field
    primary_entity = spec["primary"]["entity"]
    if date_field in (spec["primary"].get("properties") or []):
        return primary_entity, date_field
    for j in spec.get("joins") or []:
        if date_field in (j.get("properties") or []):
            return j["entity"], date_field
    # Not directly selected on any entity (e.g. a role-detected column that
    # wasn't in the originally requested field list) — fall back to primary;
    # preview_column will simply come back empty rather than erroring.
    return primary_entity, date_field


def fetch_date_column(
    client: _ColumnFetcher,
    entity_name: str,
    date_field: str,
    date_filter: tuple[Any, Any] | None = None,
) -> pd.Series:
    """Thin wrapper over a metadata-service client's ``preview_column`` — the
    cheap, paginated, single-column pull used to build the date union."""
    return client.preview_column(entity_name, date_field, date_filter=date_filter)
