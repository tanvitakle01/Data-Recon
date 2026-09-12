"""Contract lifecycle API: compile -> validate -> approve, plus discovery.

The LLM (Azure AI Foundry compile phase) only ever produces the draft
returned by ``/compile``. Everything else is deterministic. Approval is an
explicit human step — there is no automatic promotion.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.API_conn.connectors import registry
from backend.recon_engine import service
from backend.recon_engine.compiler import ContractCompilerError
from backend.recon_engine.llm import get_last_llm_outcome, reset_llm_outcome
from backend.recon_engine.interface_index import read_interface_index as _read_interface_index
from backend.recon_engine.mapping_resolution import resolve_mapping as _resolve_mapping
from backend.recon_engine.mapping_sheet_parser import parse_mapping_sheet as _parse_sheet
from backend.recon_engine.sheet_identifier import identify_systems as _identify_systems
from backend.recon_engine.models.contract import DraftContract
from backend.recon_engine.models.rules import BusinessRule, BusinessRules
from backend.recon_engine.operations import list_operations
from backend.recon_engine.storage import contract_store
# The live entity lists the entity/join gating needs, loaded exactly once in one
# place so this route and /entity-join/parse can never diverge on what "live" means.
from backend.routes.entity_join import live_entity_catalog

router = APIRouter(prefix="/api/recon", tags=["recon-contracts"])

# TEMP DIAGNOSTIC (422 investigation on /contracts/compile) — remove alongside
# the handler in main.py once the root cause is confirmed and fixed.
_diag_log = logging.getLogger("recon.diagnostics")


class CompileRequest(BaseModel):
    # Either the full parsed-sheet payload from /mapping-sheet/parse (dict) or
    # a plain list of mapping rows (legacy/simple form).
    mapping_sheet: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=list)
    # Legacy free-text instructions. Only used when every structured list
    # below is empty — see BusinessRules / service.compile_draft.
    rules: str = ""
    # Structured Business Rules Builder output (preferred over `rules`).
    transformation_rules: list[BusinessRule] = Field(default_factory=list)
    matching_rules: list[BusinessRule] = Field(default_factory=list)
    filter_rules: list[BusinessRule] = Field(default_factory=list)
    # Structured aggregation rules ({source_field, aggregation}). Applied
    # deterministically.
    aggregation_rules: list[dict[str, Any]] = Field(default_factory=list)
    # The Rules step's confirmed field mapping ({source_field, target_field}),
    # and (once approved on the Mapping Review page) the deterministic
    # matching engine's output — attached onto the draft server-side, never
    # decided by the compiler. See service.compile_draft.
    business_key: list[dict[str, Any]] = Field(default_factory=list)
    compare_fields: list[dict[str, Any]] = Field(default_factory=list)
    value_mappings: list[dict[str, Any]] = Field(default_factory=list)
    source_schema: list[str]
    target_schema: list[str]
    comparison_type: str
    source_type: str
    target_type: str
    actor: str = "system"

    def business_rules(self) -> BusinessRules:
        return BusinessRules(
            transformation_rules=self.transformation_rules,
            matching_rules=self.matching_rules,
            filter_rules=self.filter_rules,
        )


class ValidateRequest(BaseModel):
    draft: dict[str, Any]
    source_columns: list[str]
    target_columns: list[str]
    source_sample: list[dict[str, Any]] = Field(default_factory=list)
    target_sample: list[dict[str, Any]] = Field(default_factory=list)
    actor: str = "system"


class ApproveRequest(BaseModel):
    draft: dict[str, Any]
    approved_by: str
    contract_id: str | None = None


@router.get("/operations")
def get_operations() -> dict[str, Any]:
    """Discovery: the allow-listed operation registry."""
    return {"operations": list_operations()}


# ── mapping-sheet parsing ────────────────────────────────────────────────────

@router.post("/mapping-sheet/interfaces")
async def read_mapping_sheet_interfaces(file: UploadFile = File(...)) -> dict[str, Any]:
    """Read an uploaded mapping workbook's INTERFACE INDEX (no field tables).

    A mapping workbook holds many interfaces, one worksheet each, indexed by an
    "Interfaces" sheet. This returns that list — each interface's ``IBP Record``
    name plus the worksheet it resolves to — so Step 1 can offer the interfaces
    as Dataset Type choices and later parse only the chosen one.

    Deterministic: no LLM, and record -> sheet resolution never guesses. An
    interface that doesn't land on exactly one worksheet comes back
    ``status="broken"``. A workbook with no usable index falls back to its own
    worksheet NAMES as the interface list (``indexed=false``, plus a warning
    saying why) — so every sheet stays reachable rather than the upload being
    reduced to one dataset.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded mapping sheet is empty.")

    filename = file.filename or "mapping-sheet"
    try:
        index = _read_interface_index(content, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read the mapping workbook.")

    return {"filename": filename, **index}


@router.post("/mapping-sheet/parse")
async def parse_mapping_sheet(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
) -> dict[str, Any]:
    """Parse an uploaded mapping sheet (xlsx/xls/csv) into structured JSON.

    Deterministic and lossless: the selected worksheet is returned as
    ``headers`` + ``rows`` with every column and value preserved, plus
    header-based inferences (``mapping_candidates``, ``transformation_notes``,
    ``join_conditions``, ``filters``) when such columns are present. No fixed
    column names are assumed, and no contract, operation, or rule is generated
    here — interpretation is the contract compiler's job. The payload is
    ready to send as ``mapping_sheet`` to ``/contracts/compile``.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded mapping sheet is empty.")

    filename = file.filename or "mapping-sheet"
    try:
        parsed = _parse_sheet(content, filename=filename, sheet_name=sheet_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=400, detail="Could not parse the mapping sheet file.")

    return {"filename": filename, **parsed}


class IdentifyRequest(BaseModel):
    # The parsed-sheet payload from /mapping-sheet/parse (dict), or plain rows.
    mapping_sheet: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)
    # Also identify which ENTITIES to fetch per side and how to join them. Opt-in
    # because it costs a live $metadata read per configured connector: the
    # entities must be gated against each connector's live-discovered list, so
    # the lists have to be loaded. The wizard always asks for it; callers that
    # only want connector/field identification can leave it off and pay nothing.
    include_entities: bool = False


@router.post("/mapping-sheet/identify")
def identify_mapping_sheet(req: IdentifyRequest) -> dict[str, Any]:
    """Infer which source/target connectors, candidate fields, and (opt-in)
    entities + join a parsed sheet describes, constrained to the configured
    connector allow-list.

    The connector the LLM may pick is limited to configured & enabled
    connectors; anything else is returned as evidence-bearing ``unidentified``
    (a warning), never coerced to the nearest match. Degrades to an empty
    result on any LLM failure rather than raising — the human then selects the
    connector manually. Field validation against live schema happens on the
    frontend once a side's connector has loaded its schema.

    With ``include_entities``, the same single LLM call also returns each side's
    entities/join, gated against that side's connector's live entity list. It
    pre-populates the Join Builder canvas — it never bypasses it.
    """
    reset_llm_outcome()  # clear any prior provider outcome for this request

    catalog: dict[str, list[str]] | None = None
    catalog_warnings: list[str] = []
    if req.include_entities:
        kinds = [c["kind"] for c in registry.get_configured_connectors()]
        catalog, catalog_warnings = live_entity_catalog(kinds)

    result = _identify_systems(req.mapping_sheet, catalog)
    if catalog_warnings:
        result["warnings"] = [*result.get("warnings", []), *catalog_warnings]
    return result


class MappingResolutionRequest(BaseModel):
    # The parsed-sheet payload from /mapping-sheet/parse (dict), or plain rows.
    mapping_sheet: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)
    # Header bindings only — no data rows. Both must be populated (this step
    # only runs once source AND target datasets are uploaded/fetched).
    source_columns: list[str]
    target_columns: list[str]


@router.post("/mapping-resolution/resolve")
def resolve_mapping_endpoint(req: MappingResolutionRequest) -> dict[str, Any]:
    """Sequential AI mapping resolution: mapping sheet + real headers -> ops.

    Five chained LLM calls (header-level filter extraction -> relevant
    fields -> enriched fields -> transformation chain -> deterministic
    operations), run automatically with no human-approval pause between
    steps — see ``recon_engine.mapping_resolution``.
    The returned ``operations`` use the same ``{op, field, params}`` shape as
    ``/contracts/compile``'s ``draft.operations``, ready to feed the Recipe
    Editor. Never sets ``business_key``/``compare_fields`` — those stay
    human-owned via the Mapping Editor, untouched by this endpoint.
    """
    reset_llm_outcome()
    return _resolve_mapping(req.mapping_sheet, req.source_columns, req.target_columns)


@router.post("/contracts/compile")
def compile_contract(req: CompileRequest) -> dict[str, Any]:
    # TEMP DIAGNOSTIC — proves the request reached here at all (i.e. it PASSED
    # Pydantic validation). If a 422 is happening before this log line prints,
    # it is FastAPI's own request-validation 422 (see main.py's handler for the
    # loc/msg/type detail) — not this endpoint's ContractCompilerError path.
    mapping_sheet_summary = (
        {"type": "dict", "keys": sorted(req.mapping_sheet.keys())}
        if isinstance(req.mapping_sheet, dict)
        else {"type": "list", "len": len(req.mapping_sheet)}
    )
    _diag_log.info(
        "compile_contract: request validated OK. mapping_sheet=%s rules_len=%d "
        "source_schema=%s target_schema=%s comparison_type=%r source_type=%r target_type=%r",
        mapping_sheet_summary, len(req.rules or ""), req.source_schema, req.target_schema,
        req.comparison_type, req.source_type, req.target_type,
    )
    reset_llm_outcome()  # clear any prior provider outcome for this request
    try:
        draft, degraded_reason = service.compile_draft(
            mapping_sheet=req.mapping_sheet,
            rules=req.rules,
            business_rules=req.business_rules(),
            aggregation_rules=req.aggregation_rules,
            business_key=req.business_key,
            compare_fields=req.compare_fields,
            value_mappings=req.value_mappings,
            source_schema=req.source_schema,
            target_schema=req.target_schema,
            comparison_type=req.comparison_type,
            source_type=req.source_type,
            target_type=req.target_type,
            actor=req.actor,
        )
        _diag_log.info(
            "compile_contract: compiler=%s degraded=%s degraded_reason=%r",
            draft.compiler, degraded_reason is not None, degraded_reason,
        )
    except ContractCompilerError as exc:
        # An Azure AI Foundry failure no longer reaches here —
        # service.compile_draft() degrades to the deterministic stub compiler
        # automatically. This branch now means the CONTENT was rejected by
        # whichever compiler actually ran (e.g. no resolvable business-key
        # fields in mapping_sheet) — a genuine 422, not a provider
        # availability issue.
        # TEMP DIAGNOSTIC — remove alongside the handler in main.py.
        _diag_log.info(
            "compile_contract: ContractCompilerError -> 422. detail=%r mapping_sheet=%s",
            str(exc), mapping_sheet_summary,
        )
        raise HTTPException(status_code=422, detail=str(exc))
    outcome = get_last_llm_outcome()
    return {
        "draft": draft.model_dump(mode="json"),
        "degraded": degraded_reason is not None,
        "degraded_reason": degraded_reason,
        # LLM provider failover surface (spec points 4, 5, 6). ``provider`` is
        # who actually produced the draft ("azure_foundry", or the
        # deterministic "stub" when the provider was unavailable).
        "provider": (outcome.provider_used if outcome and outcome.provider_used else draft.compiler),
        "preferred_provider": outcome.preferred if outcome else "azure_foundry",
        "fallback": bool(outcome and outcome.fallback_occurred),
        "provider_notice": outcome.notice if outcome else None,
    }


@router.post("/contracts/validate")
def validate_contract(req: ValidateRequest) -> dict[str, Any]:
    report = service.validate_draft(
        req.draft,
        source_columns=req.source_columns,
        target_columns=req.target_columns,
        source_sample=pd.DataFrame(req.source_sample),
        target_sample=pd.DataFrame(req.target_sample),
        actor=req.actor,
    )
    return report


@router.post("/contracts/approve")
def approve(req: ApproveRequest) -> dict[str, Any]:
    try:
        contract = service.approve_contract(
            req.draft, approved_by=req.approved_by, contract_id=req.contract_id
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Approval failed: {exc}")
    return {"contract": contract.model_dump(mode="json")}


@router.get("/contracts/{contract_id}")
def get_versions(contract_id: str) -> dict[str, Any]:
    versions = contract_store.list_versions(contract_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"No transformation rules '{contract_id}'.")
    return {"versions": [c.model_dump(mode="json") for c in versions]}


@router.get("/contracts/{contract_id}/approved")
def get_approved(contract_id: str) -> dict[str, Any]:
    contract = contract_store.get_latest_approved(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="No approved version.")
    return {"contract": contract.model_dump(mode="json")}
