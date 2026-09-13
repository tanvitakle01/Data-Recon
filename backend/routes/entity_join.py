"""Entity/join free-text fallback — Stage-1 stub.

Stage-1 is file-upload only, so there is no live connector to fetch an entity
list from. ``live_entity_catalog`` always returns an empty catalog (with a
per-kind warning) — the same "connector metadata unreachable" degrade path
``routes/contracts.py`` and ``recon_engine/sheet_identifier.py`` already handle
for a live connector that fails to respond, so entity/join gating simply never
pre-populates the Join Builder canvas; the user names entities/joins by hand
instead. The ``/parse`` and ``/planning-areas`` HTTP endpoints below are kept
for API-shape compatibility but are not mounted in ``main.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.recon_engine.entity_join_parser import parse_entity_join

logger = logging.getLogger("recon.entity_join")

router = APIRouter(prefix="/api/recon/entity-join", tags=["recon-entity-join"])


def entities_for(kind: str) -> list[dict[str, Any]]:
    """No live connector exists in Stage-1 — always raises."""
    raise ValueError(f"No live connector configured for kind {kind!r}; file upload only.")


def live_entity_catalog(kinds: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Always empty in Stage-1 — see module docstring."""
    warnings = [
        f"Could not load the live {kind.upper()} entity list, so any entities the "
        f"sheet names for that side aren't pre-placed: no live connector configured."
        for kind in kinds
    ]
    return {}, warnings


class ParseRequest(BaseModel):
    kind: str
    text: str = ""
    planning_area: str | None = None


@router.post("/parse")
def parse(req: ParseRequest) -> dict[str, Any]:
    """Parse a plain-language entity/join instruction into a canvas-ready spec."""
    try:
        entities = entities_for(req.kind)
    except Exception as exc:  # noqa: BLE001 — degrade, never 500 the wizard
        return {
            "primary": None,
            "entities": [],
            "join_type": None,
            "keys": None,
            "unresolved": [],
            "planning_area": None,
            "ambiguous": [],
            "warnings": [f"Could not load {req.kind} entities: {exc}"],
            "degraded": True,
            "degraded_reason": str(exc),
        }
    return parse_entity_join(
        req.text,
        entities,
        (req.kind or "").strip().lower(),
        (req.planning_area or "").strip() or None,
    )


@router.get("/planning-areas")
def planning_areas(kind: str) -> dict[str, Any]:
    """No connector in Stage-1 partitions by planning area — always empty."""
    return {"planning_areas": [], "degraded": False, "degraded_reason": None}
