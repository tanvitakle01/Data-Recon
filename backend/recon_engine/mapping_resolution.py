"""Sequential AI mapping resolution — mapping sheet + real headers -> ops.

Runs AFTER a mapping sheet has been parsed (``mapping_sheet_parser.py``) and
BOTH source and target datasets have been uploaded/fetched. Only the real
header bindings (column names) of source and target are used as grounding —
never full data rows. Five LLM calls run IN SEQUENCE, each one's
deterministically-gated output feeding the next as input:

    0. extract_header_filters   — the mapping sheet's free-text preamble
                                   (above the field table; e.g. banner rows
                                   labelled "Filter:"/"Task:"/"Batch:"/
                                   "Remarks:") -> sheet-level filter
                                   candidates not tied to any one mapping
                                   row, emitted in the SAME shape as
                                   mapping_candidates so step 1 folds them in.
    1. select_relevant_fields   — mapping sheet (+ step 0's candidates) ->
                                   only the rows relevant to THIS
                                   source/target header pair.
    2. enrich_relevant_fields   — each relevant row -> real source column,
                                   source table, datatype, description.
    3. build_transformation_chain — enriched fields -> an ordered list of
                                   transformation intents (filter, date
                                   rebucket, aggregate, ...).
    4. compile_deterministic_operations — the chain -> allow-listed
                                   ``{op, field, params}`` entries using real
                                   source column names. Executable directly by
                                   the deterministic engine; no further LLM
                                   call consumes this output.

Runs fully automatically (auto-mode): no human-approval pause between steps.
This is entirely separate from, and never sets, ``business_key`` /
``compare_fields`` (see ``models.contract.ContractBody``'s docstring) — those
remain exclusively human-owned via the wizard's Mapping Editor.

Same safety posture as ``sheet_identifier.py`` / ``field_mapper.py`` /
``groq_compiler.py``: the same Azure-AI-Foundry-only ``build_llm_client()``,
every name existence-gated against the real schema, every operation
allow-list-gated against the operations registry, and every step degrades
(never raises) on failure so the wizard is never blocked.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.recon_engine.config import get_settings
from backend.recon_engine.llm import build_llm_client, get_last_llm_outcome
from backend.recon_engine.operations import get_operation, is_allowed, list_operations

logger = logging.getLogger("recon.mapping_resolution")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _resolve_column(name: str | None, columns: list[str]) -> str | None:
    """Resolve a name to a real column (exact, then case/punctuation-insensitive)."""
    if not name:
        return None
    name = str(name).strip()
    if name in columns:
        return name
    lookup = {_norm(c): c for c in columns}
    return lookup.get(_norm(name))


def _sheet_candidates_and_rows(
    mapping_sheet: dict[str, Any] | list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pull ``(mapping_candidates, rows)`` out of a parsed-sheet payload.

    ``mapping_candidates`` is the deterministic, per-row extraction already
    produced by ``mapping_sheet_parser.parse_mapping_sheet`` (row_index,
    source_field, target_field, technical_field, description, transformation,
    join_condition, filter) — nothing here re-derives it. A legacy plain-list
    ``mapping_sheet`` (no parser metadata) yields no candidates, which simply
    means step 1 finds nothing relevant rather than crashing.
    """
    if isinstance(mapping_sheet, dict):
        candidates = mapping_sheet.get("mapping_candidates")
        rows = mapping_sheet.get("rows")
        return (
            candidates if isinstance(candidates, list) else [],
            rows if isinstance(rows, list) else [],
        )
    return [], mapping_sheet if isinstance(mapping_sheet, list) else []


def _degraded(reason: str) -> dict[str, Any]:
    return {"degraded": True, "degraded_reason": reason, "provider": None}


def _call_llm(system_prompt: str, user_payload: dict[str, Any]) -> tuple[Any | None, str | None]:
    """One chat-completion call. Returns ``(payload, error)`` — never raises."""
    try:
        client = build_llm_client()
        payload = client.complete_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
            ]
        )
        return payload, None
    except Exception as exc:  # noqa: BLE001 — degradation is the contract
        return None, str(exc)


# ── Step 0: header-level filter extraction ───────────────────────────────────

_HEADER_FILTERS_PROMPT = """You are the first step of a reconciliation
mapping-resolution pipeline. You receive the RAW grid of rows that sit ABOVE
the mapping sheet's field table ("preamble_rows", a list of rows, each row a
list of cell values in column order — banner text, titles, and sheet-level
metadata) plus the REAL column names present on the source dataset
("source_columns").

Enterprise mapping workbooks sometimes state a sheet-level selection/filter
condition in this preamble — near a cell reading roughly "Filter", "Task",
"Batch", or "Remarks" — that governs which rows of the SOURCE data
participate at all, e.g. "AUART = 1", "VBELN starts with 5*", "Batch: only
document type ZOR". This is different from a per-row Transformation/Filter
note in the field table itself: it is NOT about one mapped field pairing, it
applies to the whole dataset.

Find any such condition. For each one you find, extract:
  - "raw_condition_text": the EXACT condition text, copied verbatim from a
    preamble cell — never paraphrased, never invented, never combined from
    multiple cells.
  - "field_guess": the field/column name the condition text itself names
    (e.g. "AUART" in "AUART = 1", "VBELN" in "VBELN starts with 5*") — copied
    from the condition text, not looked up against "source_columns" yourself.

If you find nothing that fits, or you are not confident a cell is actually a
sheet-level filter condition (as opposed to a title, a date, an author name,
or other banner text), return an empty list — never guess.

Respond with a single JSON object only, no prose/markdown/code fences:
{"header_filters": [{"raw_condition_text": "...", "field_guess": "..."}, ...]}
"""


def _preamble_rows(mapping_sheet: dict[str, Any] | list[dict[str, Any]]) -> list[list[Any]]:
    if not isinstance(mapping_sheet, dict):
        return []
    metadata = mapping_sheet.get("metadata")
    if not isinstance(metadata, dict):
        return []
    preamble = metadata.get("preamble_rows")
    return preamble if isinstance(preamble, list) else []


def extract_header_filters(
    mapping_sheet: dict[str, Any] | list[dict[str, Any]],
    source_columns: list[str],
) -> dict[str, Any]:
    """LLM call 0: mine sheet-level filter conditions out of the preamble.

    Emits survivors in the SAME shape as ``mapping_sheet_parser``'s
    ``mapping_candidates`` (with a synthetic negative ``row_index`` so they
    can never collide with a real table row) so ``select_relevant_fields``
    can fold them into its existing relevance judgment untouched.
    """
    preamble_rows = _preamble_rows(mapping_sheet)
    if not preamble_rows:
        return {
            "header_filter_candidates": [],
            "degraded": False,
            "degraded_reason": None,
            "provider": None,
        }

    flattened = _norm(" ".join(str(cell) for row in preamble_rows for cell in row if cell not in (None, "")))

    payload, error = _call_llm(
        _HEADER_FILTERS_PROMPT,
        {"preamble_rows": preamble_rows, "source_columns": source_columns},
    )
    if error is not None:
        logger.warning("extract_header_filters failed: %s", error)
        return {"header_filter_candidates": [], **_degraded(f"Header-filter extraction failed: {error}")}

    raw_filters = payload.get("header_filters") if isinstance(payload, dict) else None
    seen: set[tuple[str, str]] = set()
    candidates: list[dict[str, Any]] = []
    for item in raw_filters if isinstance(raw_filters, list) else []:
        if not isinstance(item, dict):
            continue
        raw_text = str(item.get("raw_condition_text") or "").strip()
        if not raw_text or _norm(raw_text) not in flattened:
            continue  # never invent condition text — must be verbatim in the preamble
        field = _resolve_column(item.get("field_guess"), source_columns)
        if not field:
            continue  # skip if unresolvable — no real field, no usable filter
        key = (field, raw_text)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "row_index": -(len(candidates) + 1),
                "source_field": None,
                "target_field": None,
                "technical_field": field,
                "description": None,
                "transformation": None,
                "join_condition": None,
                "filter": raw_text,
                "is_header_filter": True,
            }
        )

    outcome = get_last_llm_outcome()
    return {
        "header_filter_candidates": candidates,
        "degraded": False,
        "degraded_reason": None,
        "provider": outcome.provider_used if outcome and outcome.provider_used else None,
    }


# ── Step 1: relevant fields ──────────────────────────────────────────────────

_RELEVANT_FIELDS_PROMPT = """You are a step of a reconciliation
mapping-resolution pipeline. You receive a mapping sheet's deterministically
extracted candidate rows ("mapping_candidates", each with a "row_index",
"source_field", "target_field", "technical_field", "description",
"transformation", "join_condition", "filter") plus the REAL column names
actually present on the uploaded source and target datasets
("source_columns", "target_columns").

Your ONLY job: decide which candidate rows are ACTUALLY RELEVANT to
reconciling THIS specific source dataset against THIS specific target
dataset — i.e. the row's field plausibly corresponds to a real source or
target column (allowing for naming variants: "Product ID" vs "PRDID",
"VBAP-MATNR" vs "Material"), OR the row carries a filter/join condition that
governs which rows participate. Rows about fields that don't exist on either
side at all are NOT relevant — drop them.

Respond with a single JSON object only, no prose/markdown/code fences:
{"relevant_row_indices": [<row_index values from mapping_candidates that are relevant>, ...]}
Only return indices that are present in the given "mapping_candidates" list.
"""


def select_relevant_fields(
    mapping_sheet: dict[str, Any] | list[dict[str, Any]],
    source_columns: list[str],
    target_columns: list[str],
    header_filter_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """LLM call 1: narrow the mapping sheet to rows relevant to this dataset pair.

    ``header_filter_candidates`` (step 0's output, same shape as
    ``mapping_candidates``) are folded into the same relevance judgment — the
    model decides whether a sheet-level header filter is actually plausible
    for THIS source/target pair exactly like it does for a table row.
    """
    candidates, rows = _sheet_candidates_and_rows(mapping_sheet)
    all_candidates = candidates + list(header_filter_candidates or [])
    if not all_candidates:
        return {
            "relevant_candidates": [],
            "relevant_rows": [],
            "degraded": False,
            "degraded_reason": None,
            "provider": None,
        }

    payload, error = _call_llm(
        _RELEVANT_FIELDS_PROMPT,
        {
            "mapping_candidates": all_candidates,
            "source_columns": source_columns,
            "target_columns": target_columns,
        },
    )
    if error is not None:
        logger.warning("select_relevant_fields failed: %s", error)
        return {"relevant_candidates": [], "relevant_rows": [], **_degraded(
            f"Relevant-field selection failed: {error}"
        )}

    raw_indices = payload.get("relevant_row_indices") if isinstance(payload, dict) else None
    valid_by_index = {c.get("row_index"): c for c in all_candidates if isinstance(c, dict)}
    seen: set[int] = set()
    relevant_candidates: list[dict[str, Any]] = []
    for idx in raw_indices if isinstance(raw_indices, list) else []:
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            continue
        if idx in valid_by_index and idx not in seen:
            seen.add(idx)
            relevant_candidates.append(valid_by_index[idx])

    # Positionally aligned 1:1 with relevant_candidates (step 2 assumes "same
    # order") — a header-filter candidate's row_index has no entry in `rows`
    # (it isn't a real table row), so it gets an empty placeholder instead of
    # being silently dropped, which would desync the two lists.
    relevant_rows = [
        rows[c["row_index"]] if isinstance(c.get("row_index"), int) and 0 <= c["row_index"] < len(rows) else {}
        for c in relevant_candidates
    ]

    outcome = get_last_llm_outcome()
    return {
        "relevant_candidates": relevant_candidates,
        "relevant_rows": relevant_rows,
        "degraded": False,
        "degraded_reason": None,
        "provider": outcome.provider_used if outcome and outcome.provider_used else None,
    }


# ── Step 2: enrich relevant fields ───────────────────────────────────────────

_ENRICH_FIELDS_PROMPT = """You are a step of a reconciliation
mapping-resolution pipeline. You receive the mapping sheet's relevant
candidate rows ("relevant_candidates", each with "row_index", "source_field",
"target_field", "technical_field", "description"), the FULL raw row for each
(the sheet's original columns and values, "relevant_rows", same order as
"relevant_candidates" — it may carry additional columns such as a table name
or data type that aren't in "relevant_candidates"), and the REAL source
column names ("source_columns").

For EACH relevant candidate, resolve:
  - "source_column": the EXACT entry from "source_columns" this row refers to
    (resolve "technical_field" like "VBAP-MATNR" or "source_field" like
    "Material" to the real column; case/spacing differences are fine, but the
    value you output MUST be copied verbatim from "source_columns"). If you
    cannot confidently resolve one, output null — never invent a name.
  - "source_table": the source table name, if evident (e.g. "VBAP" from
    "VBAP-MATNR", or a dedicated table/table-name column in the raw row).
    Null if not evident.
  - "datatype": the field's data type, if a column in the raw row states one
    (e.g. "Data Type", "Type"). Null if not evident — never guess.
  - "description": the field's business description (from "description", or
    another descriptive column in the raw row, or the business label itself
    as a fallback).

Respond with a single JSON object only, no prose/markdown/code fences:
{"enriched_fields": [
  {"row_index": <int>, "source_column": "<exact source_columns entry, or null>",
   "source_table": "<string or null>", "datatype": "<string or null>",
   "description": "<string or null>"},
  ...
]}
One entry per row_index in "relevant_candidates".
"""


def enrich_relevant_fields(
    relevant_candidates: list[dict[str, Any]],
    relevant_rows: list[dict[str, Any]],
    source_columns: list[str],
) -> dict[str, Any]:
    """LLM call 2: resolve each relevant row to a real source column + metadata.

    Every relevant candidate that does NOT come back bound to a real source
    column is reported in ``pending_confirmation`` rather than only dropped.
    Dropping is still what happens to the *operation* (a column is never
    invented), but a silent drop is indistinguishable from "there was nothing
    to bind" — and the auto-approve gate has to be able to tell those apart and
    name the specific field it could not bind. See ``resolve_mapping``.
    """
    if not relevant_candidates:
        return {
            "enriched_fields": [],
            "pending_confirmation": [],
            "degraded": False,
            "degraded_reason": None,
            "provider": None,
        }

    payload, error = _call_llm(
        _ENRICH_FIELDS_PROMPT,
        {
            "relevant_candidates": relevant_candidates,
            "relevant_rows": relevant_rows,
            "source_columns": source_columns,
        },
    )
    if error is not None:
        logger.warning("enrich_relevant_fields failed: %s", error)
        return {
            "enriched_fields": [],
            "pending_confirmation": [],
            **_degraded(f"Field enrichment failed: {error}"),
        }

    raw_fields = payload.get("enriched_fields") if isinstance(payload, dict) else None
    valid_indices = {c.get("row_index") for c in relevant_candidates if isinstance(c, dict)}

    # row_index -> the sheet's own label for that row, for a human-readable
    # "could not bind X" message rather than a bare row number.
    labels: dict[int, str] = {}
    for cand in relevant_candidates:
        if not isinstance(cand, dict):
            continue
        try:
            idx = int(cand.get("row_index"))
        except (TypeError, ValueError):
            continue
        labels[idx] = str(
            cand.get("source_field")
            or cand.get("technical_field")
            or cand.get("target_field")
            or f"row {idx}"
        ).strip()

    pending: list[dict[str, Any]] = []
    enriched: list[dict[str, Any]] = []
    for item in raw_fields if isinstance(raw_fields, list) else []:
        if not isinstance(item, dict):
            continue
        row_index = item.get("row_index")
        try:
            row_index = int(row_index)
        except (TypeError, ValueError):
            continue
        if row_index not in valid_indices:
            continue
        declared = item.get("source_column")
        source_column = _resolve_column(declared, source_columns)
        if not source_column:
            # never invent a source column — report it instead of only dropping
            pending.append(
                {
                    "row_index": row_index,
                    "field": labels.get(row_index, f"row {row_index}"),
                    "declared_column": str(declared).strip() if declared else None,
                    "reason": (
                        f"the mapping sheet declares source column "
                        f"'{str(declared).strip()}', which is not in the uploaded source data"
                        if declared
                        else "no source column could be resolved for this field"
                    ),
                }
            )
            continue
        enriched.append(
            {
                "row_index": row_index,
                "source_column": source_column,
                "source_table": (str(item.get("source_table")).strip() or None)
                if item.get("source_table")
                else None,
                "datatype": (str(item.get("datatype")).strip() or None) if item.get("datatype") else None,
                "description": (str(item.get("description")).strip() or None)
                if item.get("description")
                else None,
            }
        )

    # A relevant candidate the model never returned at all is just as unbound as
    # one it returned with an unresolvable column — both leave a field the sheet
    # declared with nothing behind it.
    answered = {e["row_index"] for e in enriched} | {p["row_index"] for p in pending}
    for idx in sorted(valid_indices - answered):
        if idx is None:
            continue
        pending.append(
            {
                "row_index": idx,
                "field": labels.get(idx, f"row {idx}"),
                "declared_column": None,
                "reason": "no source column could be resolved for this field",
            }
        )

    outcome = get_last_llm_outcome()
    return {
        "enriched_fields": enriched,
        "pending_confirmation": pending,
        "degraded": False,
        "degraded_reason": None,
        "provider": outcome.provider_used if outcome and outcome.provider_used else None,
    }


# ── Step 3: transformation chain ─────────────────────────────────────────────

_TRANSFORMATION_CHAIN_PROMPT = """You are a step of a reconciliation
mapping-resolution pipeline. You receive the enriched relevant fields
("enriched_fields", each with "row_index", real "source_column",
"source_table", "datatype", "description") and the mapping sheet's relevant
candidate rows ("relevant_candidates", each carrying the original
"transformation", "filter" and "join_condition" free-text for that
"row_index", where present).

Study the transformation/filter/join-condition text across all relevant
fields and determine the correct EXECUTION order:
filter -> date_rebucket -> transform -> aggregate -> value_crosswalk.
Filters (whether they came from a per-row Filter note or a sheet-level
header condition — both look identical here, an "intent": "filter" node)
always resolve first, before anything else touches the data; a date rebucket
runs before the aggregation that groups by it. Group related instructions
(e.g. "sum X per product/plant/month") into ONE chain node with all the
row_indices it touches, rather than one node per field.

One intent needs special care: "value_crosswalk". Use it when the
transformation/filter text describes translating individual VALUES from one
representation to a corresponding target-side value via a lookup/crosswalk
table — e.g. "map plant codes to location IDs using the code table", "look
up the customer's region", "convert legacy material codes per the crosswalk
sheet". Resolving this requires seeing the ACTUAL data values (which this
step never does — only column names), so it can NEVER be expressed as a
chain primitive here; it is handled by a separate, later value-pairing step.
Use "filter" / "date_rebucket" / "transform" / "aggregate" for everything
else (renaming, casting, filtering rows, date bucketing, aggregation) —
none of those ever need to see actual values, only column names.

Respond with a single JSON object only, no prose/markdown/code fences:
{"chain": [
  {"intent": "filter" | "date_rebucket" | "transform" | "aggregate" | "value_crosswalk",
   "description": "<plain-language statement of what this node does, in terms of the real source_column names from enriched_fields>",
   "row_indices": [<row_index values from enriched_fields this node applies to>]},
  ...
]}
Order the array itself in execution order (index 0 runs first). Only
reference row_indices that appear in "enriched_fields". If there is nothing
to transform (no transformation/filter/join_condition text on any relevant
field), return {"chain": []}.
"""


# Deterministic execution-order enforcement — the model is never trusted to
# have actually ordered the chain this way itself (same posture as
# ``_bond_date_bucket_to_aggregate_group`` below). "filter" always sorts
# first regardless of whether it came from a table row or a header
# condition ("any source" — both look identical by the time they're a chain
# node). Unknown/unrecognised intents fall into the same tier as "transform",
# matching the existing default applied when the model omits "intent".
_INTENT_ORDER: dict[str, int] = {
    "filter": 0,
    "date_rebucket": 1,
    "transform": 2,
    "aggregate": 3,
    "value_crosswalk": 4,
}


def build_transformation_chain(
    enriched_fields: list[dict[str, Any]],
    relevant_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """LLM call 3: order the relevant transformation/filter intents into a chain."""
    if not enriched_fields:
        return {"chain": [], "degraded": False, "degraded_reason": None, "provider": None}

    has_notes = any(
        c.get("transformation") or c.get("filter") or c.get("join_condition")
        for c in relevant_candidates
        if isinstance(c, dict)
    )
    if not has_notes:
        return {"chain": [], "degraded": False, "degraded_reason": None, "provider": None}

    payload, error = _call_llm(
        _TRANSFORMATION_CHAIN_PROMPT,
        {"enriched_fields": enriched_fields, "relevant_candidates": relevant_candidates},
    )
    if error is not None:
        logger.warning("build_transformation_chain failed: %s", error)
        return {"chain": [], **_degraded(f"Transformation-chain resolution failed: {error}")}

    raw_chain = payload.get("chain") if isinstance(payload, dict) else None
    valid_indices = {f.get("row_index") for f in enriched_fields}

    unordered: list[dict[str, Any]] = []
    for node in raw_chain if isinstance(raw_chain, list) else []:
        if not isinstance(node, dict):
            continue
        intent = str(node.get("intent") or "transform").strip().lower()
        description = str(node.get("description") or "").strip()
        row_indices = [
            i for i in (node.get("row_indices") or []) if isinstance(i, int) and i in valid_indices
        ]
        if not description:
            continue
        unordered.append({"intent": intent, "description": description, "row_indices": row_indices})

    # Stable sort by intent tier — preserves the model's own relative order
    # *within* a tier, but never trusts it across tiers (filters always end
    # up first, etc.), regardless of what order it emitted the nodes in.
    unordered.sort(key=lambda n: _INTENT_ORDER.get(n["intent"], _INTENT_ORDER["transform"]))
    chain = [{"step": i, **node} for i, node in enumerate(unordered, start=1)]

    outcome = get_last_llm_outcome()
    return {
        "chain": chain,
        "degraded": False,
        "degraded_reason": None,
        "provider": outcome.provider_used if outcome and outcome.provider_used else None,
    }


# ── Step 4: deterministic operations (terminal — no further LLM call) ───────

_DETERMINISTIC_OPERATIONS_PROMPT = """You are the FINAL step of a
reconciliation mapping-resolution pipeline. You receive an ordered
transformation "chain" (each node: "intent", "description", "row_indices"),
the "enriched_fields" those row_indices resolve to (each with the REAL
"source_column"), and the "allowed_operations" registry (each entry's
"name", "kind", "description", "required_params", "optional_params").

For EVERY chain node, decide how to express it by following this procedure
IN ORDER — never skip a step:

1. EXACT MATCH: Does an "allowed_operations" entry, used with its params
   filled in as-is, already express this node? If so, use it.
2. SAFE GENERALIZATION (reuse, don't fork): If there's no exact match, can an
   EXISTING operation's OWN parameter schema express the node via a
   strict-superset parameterization of that SAME operation — e.g.
   "date_bucket"'s "granularity"/"anchor" params already cover
   day/week/month/quarter/year and start/end, so a "bucket to month" AND a
   "bucket to quarter-end" node both reuse "date_bucket" with different
   params, never two different operation names. "aggregate_group"'s "by"
   (any number of columns) and "aggregations" (any number of measures,
   func: sum/count/average/min/max/first) likewise cover every multi-key,
   multi-measure grouping in ONE call — never split one grouping across
   several aggregate operations. If an existing operation's params can
   express the node this way, reuse it — do NOT invent a new operation name
   for something an existing one's parameters already cover.
3. NEW PRIMITIVE PROPOSAL (last resort only): Only when NEITHER of the above
   covers the node, do NOT fabricate an ad hoc operation name for immediate
   use — the registry is a closed, human-curated allow-list and an unlisted
   name would simply fail to execute. Instead add ONE entry to
   "proposed_operations" describing the primitive for human review: `{"name":
   "<a short, descriptive, not-already-in-the-registry name>", "kind":
   "transform"|"filter"|"aggregate", "params": {"<param name>": "<what it
   holds>"}, "contract": "<one sentence: what it does and precisely why no
   existing operation or generalization of one covers it>", "row_indices":
   [<the chain node's row_indices>]}`. Do NOT add anything to "operations"
   for that node — a proposal is not an executable step until a human
   approves and implements it.

Hard rules (apply to every "operations" entry, regardless of which step above
produced it):
1. "op" MUST be the exact name of an EXISTING entry in "allowed_operations" —
   never a name from "proposed_operations", never invented, guessed,
   renamed, or abbreviated.
2. "field" (and any field-shaped param) MUST be copied verbatim from the
   "source_column" values in "enriched_fields" — never a mapping-sheet
   label, never a technical table.field reference, never a literal data
   value.
3. This output is executed directly with NO further interpretation — never
   include SQL, Python, pandas, or any other code; only allow-listed
   operation names and their data parameters.
4. Preserve execution order: operations from an earlier chain node come
   before operations from a later one.
5. When a node buckets a date (via "date_bucket") and any node aggregates by
   that same date dimension (via "aggregate_group"), treat the two as ONE
   bonded unit: the bucketed field MUST be one of "aggregate_group"'s "by"
   entries — never leave the aggregation grouping by a granularity the sheet
   didn't ask for (e.g. raw daily dates) when a coarser bucket was just
   computed for exactly this purpose. (This is re-checked and corrected
   deterministically after you respond, regardless of the order you emit
   the two calls in, but get it right the first time.)
6. Within a single "aggregate_group" call, a field in "by" must never also
   appear as a measure in "aggregations" — a group-by dimension and an
   aggregated measure are mutually exclusive; if the chain seems to ask for
   both, it is describing two different fields, not one.

Respond with a single JSON object only, no prose/markdown/code fences:
{"operations": [{"op": "...", "field": "..." | null, "params": {...}}, ...],
 "proposed_operations": [{"name": "...", "kind": "...", "params": {...},
  "contract": "...", "row_indices": [...]}]}
Omit "proposed_operations" (or leave it empty) when every node is covered by
an existing operation.
"""


def _bond_date_bucket_to_aggregate_group(candidates: list[dict[str, Any]]) -> None:
    """Enforce date_bucket -> aggregate_group as one bonded unit, in place.

    The model is never trusted to have wired this itself, or to have placed
    the two calls adjacently or in the "expected" order. Whenever ANY
    "date_bucket" candidate resolves to a field, EVERY "aggregate_group"
    candidate anywhere in the chain — before it, after it, adjacent or not —
    must group by that bucketed field. date_bucket rewrites the field's
    VALUES in place under the same name (it never renames), so "wiring in"
    the bucketed output is exactly "make sure this field name is in `by`" —
    inserted if the model omitted it or referenced something else for the
    date dimension.

    Position in ``candidates`` doesn't affect what actually runs: the
    executor's fixed pipeline (``build_shadow_source``) always runs every
    TRANSFORM op, date_bucket included, before any AGGREGATE op, so the
    bucketing has already happened by the time an aggregate_group — wired up
    here — reads the field, no matter which order the model emitted the two
    calls in.

    A date_bucket with no resolved field (itself invalid, dropped later) has
    nothing to wire and is skipped.
    """
    bucketed_fields = [c["field"] for c in candidates if c["op"] == "date_bucket" and c["field"]]
    if not bucketed_fields:
        return
    for candidate in candidates:
        if candidate["op"] != "aggregate_group":
            continue
        by = candidate["params"].get("by")
        by = list(by) if isinstance(by, list) else []
        for field in bucketed_fields:
            if field not in by:
                by.append(field)
        candidate["params"]["by"] = by


def _crosswalk_entries(
    crosswalk_nodes: list[dict[str, Any]], enriched_fields: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Resolve every "value_crosswalk" chain node's row_indices to the real
    source column(s) they touch, for a field to be flagged as requiring the
    (separate, data-level) value-pairing step rather than silently skipped or
    guessed at as a chain operation. One entry per distinct source column —
    a field named by more than one crosswalk node is only ever flagged once.
    """
    enriched_by_index = {f.get("row_index"): f for f in enriched_fields}
    entries: list[dict[str, Any]] = []
    seen_fields: set[str] = set()
    for node in crosswalk_nodes:
        for idx in node.get("row_indices") or []:
            enriched = enriched_by_index.get(idx)
            source_column = enriched.get("source_column") if enriched else None
            if not source_column or source_column in seen_fields:
                continue
            seen_fields.add(source_column)
            entries.append(
                {
                    "source_column": source_column,
                    "description": node.get("description") or "",
                    "row_index": idx,
                }
            )
    return entries


def compile_deterministic_operations(
    chain: list[dict[str, Any]],
    enriched_fields: list[dict[str, Any]],
    source_columns: list[str],
    header_filter_row_indices: set[int] | None = None,
) -> dict[str, Any]:
    """LLM call 4 (terminal): chain -> allow-listed, existence-gated operations.

    Follows a reuse-before-new-primitive procedure (see the prompt): exact
    registry match, then a safe superset-parameterization of an existing
    operation, and only as a last resort a NEW primitive — which is never
    auto-added to ``operations`` (the registry is closed; an unlisted name
    can't execute). A last-resort proposal is instead surfaced in
    ``proposed_operations`` for human review before it is ever implemented
    and added to the registry.

    Any "value_crosswalk" node (see ``build_transformation_chain``) is pulled
    out BEFORE the LLM ever sees this chain — resolving one requires actual
    data values, which this whole header-binding-only pipeline never has, so
    there is nothing here for even a well-behaved model to compile. Its
    field(s) are surfaced in ``requires_value_pairing`` instead of being sent
    to the operations-compiler prompt at all — a deterministic gate, not a
    prompt instruction the model could get wrong.

    A proposal whose ``row_indices`` trace back to a header-level filter
    (``header_filter_row_indices``, from ``extract_header_filters``) is
    marked ``flagged_for_shadow_test`` — never dropped either way, but a
    signal for the human-review step that this specific proposal still needs
    a shadow-mode resolve/reconcile trial (real data, run separately at
    contract-build time — this pure, data-blind function never runs one
    itself) before it can be promoted live.
    """
    header_filter_row_indices = header_filter_row_indices or set()
    crosswalk_nodes = [n for n in chain if n.get("intent") == "value_crosswalk"]
    chain_ops_nodes = [n for n in chain if n.get("intent") != "value_crosswalk"]
    requires_value_pairing = _crosswalk_entries(crosswalk_nodes, enriched_fields)

    if not chain_ops_nodes:
        return {
            "operations": [], "proposed_operations": [], "requires_value_pairing": requires_value_pairing,
            "degraded": False, "degraded_reason": None, "provider": None,
        }

    payload, error = _call_llm(
        _DETERMINISTIC_OPERATIONS_PROMPT,
        {
            "chain": chain_ops_nodes,
            "enriched_fields": enriched_fields,
            "allowed_operations": list_operations(),
        },
    )
    if error is not None:
        logger.warning("compile_deterministic_operations failed: %s", error)
        return {
            "operations": [], "proposed_operations": [], "requires_value_pairing": requires_value_pairing,
            **_degraded(f"Operation compilation failed: {error}"),
        }

    raw_ops = payload.get("operations") if isinstance(payload, dict) else None
    candidates: list[dict[str, Any]] = []
    for item in raw_ops if isinstance(raw_ops, list) else []:
        if not isinstance(item, dict):
            continue
        op_name = str(item.get("op") or "").strip()
        if not is_allowed(op_name):
            logger.warning("Dropping unresolved operation name from mapping resolution: %r", op_name)
            continue
        params = dict(item.get("params")) if isinstance(item.get("params"), dict) else {}
        raw_field = item.get("field")
        if not raw_field and "field" in params:
            # The model sometimes nests "field" inside "params" instead of at
            # the top level the registry expects — recover it rather than
            # dropping an otherwise-correct operation for a shape mismatch
            # (which previously produced both a "requires a field" error AND
            # an "unexpected param 'field'" error, guaranteeing rejection).
            raw_field = params.pop("field")
        field = _resolve_column(raw_field, source_columns) if raw_field else None
        candidates.append({"op": op_name, "field": field, "params": params})

    _bond_date_bucket_to_aggregate_group(candidates)

    operations: list[dict[str, Any]] = []
    for candidate in candidates:
        op_name, field, params = candidate["op"], candidate["field"], candidate["params"]
        errors = get_operation(op_name).validate(field, params, source_columns)
        if errors:
            logger.warning("Dropping invalid operation %r from mapping resolution: %s", op_name, errors)
            continue
        operations.append({"op": op_name, "field": field, "params": params, "enabled": True})

    raw_proposals = payload.get("proposed_operations") if isinstance(payload, dict) else None
    proposed_operations: list[dict[str, Any]] = []
    for item in raw_proposals if isinstance(raw_proposals, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        contract = str(item.get("contract") or "").strip()
        if not name or not contract:
            continue
        if is_allowed(name):
            # Already a real operation — the model should have used it
            # directly (step 1/2), not proposed it as new. Not a proposal.
            logger.warning("Dropping proposed_operation naming an existing operation: %r", name)
            continue
        kind = str(item.get("kind") or "").strip().lower()
        params_schema = item.get("params") if isinstance(item.get("params"), dict) else {}
        raw_row_indices = item.get("row_indices")
        row_indices = [i for i in raw_row_indices if isinstance(i, int)] if isinstance(raw_row_indices, list) else []
        proposal = {"name": name, "kind": kind or "transform", "params": params_schema, "contract": contract}
        if header_filter_row_indices and any(i in header_filter_row_indices for i in row_indices):
            proposal["flagged_for_shadow_test"] = True
        proposed_operations.append(proposal)

    outcome = get_last_llm_outcome()
    return {
        "operations": operations,
        "proposed_operations": proposed_operations,
        "requires_value_pairing": requires_value_pairing,
        "degraded": False,
        "degraded_reason": None,
        "provider": outcome.provider_used if outcome and outcome.provider_used else None,
    }


# ── orchestrator ──────────────────────────────────────────────────────────────

def resolve_mapping(
    mapping_sheet: dict[str, Any] | list[dict[str, Any]],
    source_columns: list[str],
    target_columns: list[str],
) -> dict[str, Any]:
    """Run the five steps in sequence; each step's output feeds the next.

    Auto-mode: no human-approval pause between steps. Never raises — any
    step's failure degrades that step to an empty result and the pipeline
    continues (e.g. no transformation chain simply means no operations).
    """
    if not get_settings().any_llm_configured:
        return {
            "header_filters": [],
            "relevant_fields": [],
            "enriched_fields": [],
            "transformation_chain": [],
            "operations": [],
            "proposed_operations": [],
            "requires_value_pairing": [],
            "pending_confirmation": [],
            **_degraded("No AI provider is configured (AZURE_FOUNDRY_MODEL) — build the recipe manually."),
        }

    warnings: list[str] = []
    provider: str | None = None

    step0 = extract_header_filters(mapping_sheet, source_columns)
    if step0.get("degraded_reason"):
        warnings.append(step0["degraded_reason"])
    provider = provider or step0.get("provider")
    header_filter_candidates = step0.get("header_filter_candidates", [])
    header_filter_row_indices = {c["row_index"] for c in header_filter_candidates}

    step1 = select_relevant_fields(
        mapping_sheet, source_columns, target_columns, header_filter_candidates=header_filter_candidates
    )
    if step1.get("degraded_reason"):
        warnings.append(step1["degraded_reason"])
    provider = provider or step1.get("provider")

    step2 = enrich_relevant_fields(
        step1.get("relevant_candidates", []), step1.get("relevant_rows", []), source_columns
    )
    if step2.get("degraded_reason"):
        warnings.append(step2["degraded_reason"])
    provider = provider or step2.get("provider")

    step3 = build_transformation_chain(step2.get("enriched_fields", []), step1.get("relevant_candidates", []))
    if step3.get("degraded_reason"):
        warnings.append(step3["degraded_reason"])
    provider = provider or step3.get("provider")

    step4 = compile_deterministic_operations(
        step3.get("chain", []),
        step2.get("enriched_fields", []),
        source_columns,
        header_filter_row_indices=header_filter_row_indices,
    )
    if step4.get("degraded_reason"):
        warnings.append(step4["degraded_reason"])
    provider = provider or step4.get("provider")

    return {
        "header_filters": header_filter_candidates,
        "relevant_fields": step1.get("relevant_candidates", []),
        "enriched_fields": step2.get("enriched_fields", []),
        "transformation_chain": step3.get("chain", []),
        "operations": step4.get("operations", []),
        # Last-resort primitives the AI could NOT express with an existing
        # operation (even via a safe generalization) — never executable,
        # never added to `operations`; surfaced for a human to review and,
        # if approved, implement as a new registry entry before first use.
        "proposed_operations": step4.get("proposed_operations", []),
        # Fields whose sheet-declared transformation is a value-level
        # crosswalk (needs real data values to resolve, never expressible as
        # a chain primitive) — left unresolved/pending here rather than
        # silently skipped or guessed at; resolved by the separate
        # value-pairing step when the caller opts into sending data to AI.
        "requires_value_pairing": step4.get("requires_value_pairing", []),
        # Fields the sheet declared that could NOT be bound to a real source
        # column (step 2). Each entry names the field and why it stayed
        # unbound. Non-empty means header binding left something unresolved —
        # the auto-approve gate refuses to auto-approve on it and names the
        # field, because an unbound field silently drops a rule the mapping
        # sheet's author intended to apply.
        "pending_confirmation": step2.get("pending_confirmation", []),
        "degraded": bool(warnings),
        "degraded_reason": "; ".join(warnings) if warnings else None,
        "provider": provider,
    }
