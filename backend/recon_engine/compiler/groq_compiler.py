"""Groq contract compiler — the LLM compile phase.

    Mapping Sheet + Rules -> Groq LLM -> Draft Transformation Contract JSON

The model is only ever asked for JSON matching the ``DraftContract`` schema; the
response is parsed and validated with ``DraftContract.model_validate``. Calling
:meth:`compile` requires ``GROQ_API_KEY`` (and the optional ``groq`` package);
without it, :meth:`compile` raises ``ContractCompilerError`` and callers should
fall back to ``StubContractCompiler`` for a deterministic draft.

Where the Groq API key is required
-----------------------------------
Only here, and only at ``compile`` time. Set ``GROQ_API_KEY`` (and optionally
``GROQ_MODEL`` / ``GROQ_BASE_URL``) in the environment. No other part of the
system — validation, approval, the deterministic engine, reconciliation —
needs Groq or any network access.

Safety invariant
----------------
The Groq response is parsed as JSON and validated into a ``DraftContract``.
The model can therefore only ever produce *data*. Any operation it names must
exist in the allow-listed registry (enforced by Gate 1). It cannot emit or run
code, SQL, pandas, or scripts of any kind.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from backend.recon_engine.compiler.base import ContractCompiler, ContractCompilerError
from backend.recon_engine.models.contract import ContractBody, DraftContract
from backend.recon_engine.models.rules import BusinessRules, normalize_business_rules
from backend.recon_engine.operations import list_operations

logger = logging.getLogger("recon.compiler.groq")

# The instruction preamble the LLM will receive. Kept here so it is reviewable
# and version-controlled rather than buried in a runtime string.
#
# Safety invariant: the model may only ever produce *data* (a DraftContract),
# and every operation it names must already exist in the allow-listed registry
# (enforced by Gate 1). The preamble below states this explicitly to reduce
# Gate 1 failures and to keep the model from ever emitting executable artifacts.
_SYSTEM_PREAMBLE = """You are a reconciliation contract compiler.

Your only job is to translate the user's business rules into "operations"
(and, when something can't be turned into an operation, "notes") — expressed
as STRICT JSON data.

NON-NEGOTIABLE SCOPE LIMIT: you NEVER decide field mapping or identifier value
mapping. Concretely:
  - "business_key" and "compare_fields" are decided by a HUMAN, in the wizard's
    Rules step, before you are ever called — NOT by you. Always output them as
    empty arrays: "business_key": [], "compare_fields": []. Anything you put
    there is discarded by the caller, so do not bother inferring it.
  - "value_mappings" (identifier value-to-value resolution, e.g. a SAP
    Material code to an IBP PRDID code, or a plant code to a location id) is
    produced by a separate deterministic matching engine, never by you. NEVER
    emit a "value_mapping" operation whose "field" is a business-key or
    compare field used for identifier resolution (e.g. "Material",
    "ProductionPlant", or their target-side counterparts) — that responsibility
    is not yours, even if a rule or the mapping sheet seems to ask for it. If a
    rule looks like it wants that, do not fabricate a mapping — append it
    verbatim to "notes" instead. "value_mapping" remains available for
    OTHER, unrelated value remaps a rule explicitly and literally spells out
    (e.g. recoding a status flag) — just never for resolving one system's
    identifier to another's.

The "mapping_sheet" input is either a plain list of mapping rows, or a parsed
worksheet object with "sheet_name", "headers", "rows", plus inferred
"mapping_candidates", "transformation_notes", "join_conditions" and "filters".
It is supplied only as BUSINESS CONTEXT to help you understand field
semantics, filters, and join conditions when deciding "operations" — it is NOT
a source of business-key or compare-field decisions (see the scope limit
above), even though its rows may carry source/target column names.

USER INSTRUCTIONS come in two possible forms — use whichever is populated:
1. "business_rules" (STRUCTURED, PREFERRED): an object with three arrays,
   "transformation_rules", "matching_rules" and "filter_rules". Each entry is
   `{"field": "<a name from the mapping sheet or a schema>", "instruction":
   "<plain-language instruction>"}`. When "business_rules" has ANY entries in
   it, it is the authoritative source of user instructions — treat it as such
   and give it priority over anything only implied by the mapping sheet.
   - "transformation_rules" describe how to change a field's value before
     comparison (e.g. normalise a format) — these typically become entries in
     "operations".
   - "matching_rules" describe equivalence/comparison behaviour between the
     source and target value of a field (e.g. two codes should be treated as
     equal, or comparison should ignore case) — these typically become a
     normalising operation on the source field (e.g. "trim_string",
     "uppercase") so the values line up before comparison, or an
     "exclude_value"/"include_value"-style operation when the rule declares
     specific values equivalent. The compare field's "match_type"/tolerance
     itself is decided by the human, not you — never invent it.
   - "filter_rules" describe which records to include or exclude — these
     typically become filter operations ("reject_null", "exclude_value",
     "include_value").
   Each rule's "field" is a name from the mapping sheet or a business label,
   NOT guaranteed to be schema-valid — resolve it exactly like a mapping-sheet
   field (see SCHEMA-VALIDITY RULES below) before referencing it anywhere in
   the output. If a rule's field cannot be confidently resolved, or its
   instruction does not correspond to any allowed operation, do NOT guess —
   append it verbatim to "notes" instead of fabricating a mapping or operation.
2. "rules" (LEGACY FREE TEXT): a single unstructured string. Only interpret
   this when "business_rules" is completely empty — it exists purely for
   backward compatibility with callers that have not adopted the structured
   Business Rules Builder yet.

Enterprise mapping sheets commonly carry THREE different names for the same
column: a human-readable label (e.g. "Product ID"), a source-side technical
reference (e.g. "VBAP-MATNR"), and a technical field name that matches the
actual target schema (e.g. "PRDID" / "I_PRDID"). None of those sheet-side
names are guaranteed to be schema-valid — "source_schema" and "target_schema"
are the ONLY authoritative lists of column names that actually exist on the
real data. A mapping row's "technical_field" is usually the one that lines up
with a "target_schema" entry (allowing for prefixes like "I_"); the
human-readable "target_field" label almost never does.

SCHEMA-VALIDITY RULES — these override anything the mapping sheet says:
1. Every operation's "field" MUST be copied verbatim from "source_schema"
   (case-insensitive match against the real schema is fine when resolving a
   mapping-sheet row's "technical_field" first, then its "source_field" as
   given — but the value you emit must be the exact real-schema spelling).
2. NEVER emit a human-readable label (e.g. "Product ID", "Location ID") or a
   table-qualified source reference (e.g. "VBAP-MATNR") as an operation's
   "field" value — those are not schema field names, only descriptions of one.
3. If a mapping-sheet row's field cannot be confidently resolved to a real
   "source_schema" entry, do not guess or invent a name — append the row's
   context to "notes" instead and omit any operation referencing it.

OUTPUT RULES — follow all of them:
1. Output valid JSON ONLY. No prose, no explanations, no comments, no markdown,
   and no code fences. The entire response must be a single JSON object.
2. The JSON object MUST conform exactly to the JSON schema provided in the user
   message under "required_output_schema". Use only the fields that schema
   defines; do not add extra fields, and do not add any provenance/bookkeeping
   fields (id, version, timestamps, approval status, compiler name) — the
   caller assigns those, never the model.
3. For every entry in "operations", the "op" value MUST be the exact name of an
   operation listed in "allowed_operations". NEVER invent, guess, rename, or
   abbreviate an operation name.
   - Use "reject_null" / "exclude_value" / "include_value" for row filters
     described in "filters" or "join_conditions" (e.g. "sales org = 5875"
     becomes "include_value" on that field with values: ["5875"]).
   - If a piece of business context (e.g. a cross-table join condition that
     the upstream extract has already resolved, like "VBAP-VBELN =
     VBAK-VBELN") does not correspond to any allowed operation, do NOT
     fabricate one — instead append it verbatim as a short line in "notes".
4. Only reference column names that appear in "source_schema" — in every
   operation's "field".
5. NEVER output SQL, Python, pandas, Spark, JavaScript, shell commands,
   scripts, or any other executable logic. You describe *what* to reconcile by
   naming allow-listed operations and their parameters — you never write *how*
   to compute it as code. (A "pattern"/"replacement" parameter for the
   allow-listed "regex_replace" op is data, and is allowed; free-form code is
   not.)
6. "notes" MUST be a single string, or null — never a list. If you have more
   than one note, join them into one string separated by "; ".

VALUE-TRANSFORMATION RULES — this is the most important section:
The Shadow_Source is rebuilt PURELY from "operations"; "notes" are never
executed. Therefore EVERY instruction that changes a source VALUE before
comparison MUST become one or more entries in "operations". It is a hard error
to describe a value transformation only in "notes". Map the common intents to
these allow-listed operations (confirm each name against "allowed_operations"):

   - "add prefix X" / "prepend X"          -> "prepend_prefix"  {"value": "X"}
   - "append X" / "add suffix X"           -> "append_suffix"   {"value": "X"}
   - "add prefix X when numeric"           -> "conditional_prefix"
                                              {"value": "X", "condition": "numeric"}
   - "replace A with B" (substring)        -> "replace_value"   {"from": "A", "to": "B"}
   - "remove leading zeros"                -> "remove_leading_zeros"
   - "uppercase" / "lowercase"             -> "uppercase" / "lowercase"
   - "trim" / "strip whitespace"           -> "trim_string"
   - "take first N chars" / positions      -> "substring"       {"start": ..., "length": ...}
   - "round to N decimals"                 -> "decimal_round"    {"decimals": N}
   - "map these codes to those" (a rule that explicitly and literally spells
     out a fixed set of value pairs, on a field that is NOT an identifier
     being resolved between systems — see the NON-NEGOTIABLE SCOPE LIMIT
     above) -> "value_mapping" {"mapping": {...}}
   - "default blanks to X"                 -> "null_to_default"  {"default": "X"}
   - "cast to string" / "cast to number"   -> "identity_cast_string" / "numeric_cast"
   - date reformat (e.g. DD.MM.YYYY)       -> "date_parse"
   - a pattern-based edit                  -> "regex_replace"    {"pattern": ..., "replacement": ...}

Order matters: emit operations in the order they must be applied (e.g. prefix
BEFORE suffix). Multiple rules on one field become multiple operations on that
field. Apply these to BOTH the mapping sheet's transformation text AND the
user's "transformation_rules".

7. NEVER use "rename_field" to change a value. "rename_field" only relabels a
   column; it does not add a prefix, strip zeros, replace text, or otherwise
   edit values. If the intent is to modify the value, use the value ops above.
8. Avoid using "rename_field" (or any op that drops a column) on a field named
   in "source_schema" unless the rule explicitly asks for it — the human's
   field mapping (business_key/compare_fields, decided outside this call) may
   depend on that column still existing by its original name after your
   operations run, and a later validation step rejects the whole contract if
   you break that.
9. "notes" is informational ONLY (unmapped context, assumptions, warnings).
   It must contain NO executable logic and NO value-transformation rule that
   should instead be an operation.

If you cannot produce a compliant contract, still return the closest valid
JSON object that conforms to the schema; never return prose describing the
problem.
"""


def _normalise_notes(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce a list-shaped "notes" into one string before schema validation.

    Despite the prompt instructing a single string, models occasionally
    return multiple observations (e.g. an unmapped join condition and an
    unmapped filter) as a JSON array instead — a semantically harmless
    deviation that would otherwise fail ``ContractBody`` validation outright
    and throw away an otherwise-correct contract. Any other shape is left
    alone; that's a genuine schema violation Gate 1 should still see.
    """
    notes = payload.get("notes")
    if isinstance(notes, list):
        joined = "; ".join(str(n) for n in notes if n not in (None, ""))
        payload = {**payload, "notes": joined or None}
    return payload


class GroqContractCompiler(ContractCompiler):
    """The LLM compile phase. Groq is the primary provider; if it hits a
    retryable error (rate limit / quota / token limit / timeout / unavailable /
    connection), the request automatically fails over to OpenAI. The draft's
    ``compiler`` provenance records whichever provider actually produced it.
    """

    name = "groq"

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        # Imported lazily: the compiler package is imported while the llm package
        # is still initialising (llm → compiler.base → compiler/__init__), so a
        # module-level import here would be a circular import.
        from backend.recon_engine.llm import build_llm_client

        self._llm = build_llm_client(groq_api_key=api_key, groq_model=model)

    @property
    def is_configured(self) -> bool:
        return self._llm.is_configured

    def _build_prompt(
        self,
        *,
        mapping_sheet: list[dict[str, Any]] | dict[str, Any],
        rules: str,
        business_rules: BusinessRules | None = None,
        source_schema: list[str],
        target_schema: list[str],
        comparison_type: str,
        source_type: str,
        target_type: str,
    ) -> list[dict[str, str]]:
        """Assemble the chat messages. Ready for the future implementation."""
        registry = list_operations()
        user_payload = {
            "comparison_type": comparison_type,
            "source_type": source_type,
            "target_type": target_type,
            "source_schema": source_schema,
            "target_schema": target_schema,
            "mapping_sheet": mapping_sheet,
            "rules": rules,
            "business_rules": normalize_business_rules(business_rules).model_dump(mode="json"),
            "allowed_operations": registry,
            # Scoped to ContractBody (compiler-owned fields only) — NOT the
            # full DraftContract schema, which also carries server-assigned
            # provenance fields (created_at, created_by, compiler,
            # approval_status) the model has no business setting. Handing the
            # model those previously caused it to emit e.g. "created_at":
            # null, which failed DraftContract validation before Gate 1 ever
            # ran.
            "required_output_schema": ContractBody.model_json_schema(),
        }
        return [
            {"role": "system", "content": _SYSTEM_PREAMBLE},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]

    # ── compile ──────────────────────────────────────────────────────────────
    def compile(
        self,
        *,
        mapping_sheet: list[dict[str, Any]] | dict[str, Any],
        rules: str,
        business_rules: BusinessRules | None = None,
        source_schema: list[str],
        target_schema: list[str],
        comparison_type: str,
        source_type: str,
        target_type: str,
    ) -> DraftContract:
        """Mapping Sheet + Rules -> Groq LLM -> validated ``DraftContract``.

        The model may only emit JSON matching the ``DraftContract`` schema. The
        JSON is validated with ``DraftContract.model_validate`` (never manually
        constructed), so anything the model produces is inert data that must
        still pass Gate 1, Gate 2, and human approval downstream.
        """
        logger.info(
            "Using compiler=%s for comparison_type=%r source_type=%r target_type=%r",
            self.name, comparison_type, source_type, target_type,
        )
        messages = self._build_prompt(
            mapping_sheet=mapping_sheet,
            rules=rules,
            business_rules=business_rules,
            source_schema=source_schema,
            target_schema=target_schema,
            comparison_type=comparison_type,
            source_type=source_type,
            target_type=target_type,
        )

        logger.info("Calling GroqContractCompiler (Groq→OpenAI failover)")
        # Tries Groq, then OpenAI on a retryable Groq failure. Raises
        # ContractCompilerError if no provider is configured / a non-retryable
        # error occurs / the response is not valid JSON, and
        # AllProvidersUnavailableError if every provider is rate-limited/down.
        payload = self._llm.complete_json(messages)
        payload = _normalise_notes(payload)

        # Validate against ContractBody first — the schema the model was
        # actually asked to fill in (compiler-owned fields only). Server-owned
        # provenance fields (created_at, created_by, compiler, approval_status)
        # are then applied on top, never taken from the model's output.
        try:
            body = ContractBody.model_validate(payload)
        except ValidationError as exc:
            logger.error("Groq output failed schema validation: %s", exc)
            raise ContractCompilerError(
                "Groq output did not match the required contract schema: " + str(exc)
            ) from exc

        # Stamp provenance with the provider that actually served the request
        # ("groq" normally, "openai" when failover kicked in).
        from backend.recon_engine.llm import get_last_llm_outcome

        outcome = get_last_llm_outcome()
        provider = outcome.provider_used if outcome and outcome.provider_used else self.name
        contract = DraftContract(**body.model_dump(), compiler=provider)
        logger.info(
            "%s produced a draft via provider=%s: business_key=%d compare_fields=%d operations=%d",
            type(self).__name__, provider,
            len(contract.business_key), len(contract.compare_fields), len(contract.operations),
        )
        return contract
