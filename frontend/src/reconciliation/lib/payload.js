import api from "../../services/api";

// Appends one reconciliation side (source or target) to a FormData in the
// shape /automap and /reconcile expect: an uploaded Excel file
// (`<role>_file` + optional `sheet_name_<role>`) for Excel datasets, or a
// JSON `<role>_rows` array for SAP-fetched datasets. Returns true if data
// was appended, false if the side has no usable payload (e.g. after a
// refresh dropped the in-memory file/rows).
export function appendDatasetSide(formData, role, roleState) {
  const dataset = roleState?.dataset;
  if (!dataset) return false;

  if (roleState.kind === "excel" && dataset.file) {
    formData.append(`${role}_file`, dataset.file);
    if (dataset.sheet) formData.append(`sheet_name_${role}`, dataset.sheet);
    return true;
  }

  if (Array.isArray(dataset.rows) && dataset.rows.length > 0) {
    formData.append(`${role}_rows`, JSON.stringify(dataset.rows));
    return true;
  }

  return false;
}

// NOTE: keyFieldPairs / buildValueMappingFormData /
// missingValueMappingRequirements lived here to drive data-level value
// pairing (/value-mapping/run and the live pre-pass). That whole stage is
// gone from the wizard — this deploy is mapping-sheet-driven only, so the
// draft contract always carries `value_mappings: []` and nothing client-side
// ships row values for pairing. The backend routes still exist if it returns.

// Sample rows for a wizard side, used both for Gate 2 replay (contract flow)
// and for sandbox preview execution (script flow): full rows when the dataset
// was fetched via SAP (kept in memory), otherwise the preview rows captured
// at upload time.
export function sampleRows(roleState, limit = 100) {
  const dataset = roleState?.dataset;
  if (!dataset) return [];
  if (Array.isArray(dataset.rows) && dataset.rows.length > 0) return dataset.rows.slice(0, limit);
  if (Array.isArray(dataset.preview)) return dataset.preview;
  return [];
}

// A properly-sized, REPRESENTATIVE sample for Gate 2 sample replay — distinct
// from sampleRows()'s small upload-preview array. That array exists for the
// Dataset Preview card's own display (backend-capped to a handful of rows,
// see routes/preview.py) and can, by pure bad luck, contain zero rows a
// legitimately selective filter/business rule would keep — Gate 2 would then
// wrongly conclude the whole pipeline drops everything, when only this thin
// sample happened not to match. When the raw file is still held in memory
// (`dataset.file` — true for a fresh Excel/CSV upload, not after a page
// refresh), re-request the SAME file from /preview with a much larger `rows`
// count instead of reusing the cached small array. `limit` mirrors the
// backend's own REPLAY_SAMPLE_MAX (backend/recon_engine/config.py) — Gate 2
// never looks at more rows than that anyway. SAP-fetched datasets already
// keep their full rows in memory (no re-fetch needed); anything without a
// live file handle falls back to whatever sampleRows() already has.
export async function gate2SampleRows(roleState, limit = 100) {
  const dataset = roleState?.dataset;
  if (!dataset) return [];
  if (Array.isArray(dataset.rows) && dataset.rows.length > 0) return dataset.rows.slice(0, limit);
  if (dataset.file) {
    try {
      const formData = new FormData();
      formData.append("file", dataset.file);
      if (dataset.sheet) formData.append("sheet_name", dataset.sheet);
      formData.append("rows", String(limit));
      const res = await api.post("/preview", formData);
      if (Array.isArray(res.data?.preview)) return res.data.preview;
    } catch {
      // Fall through to whatever sample is already cached client-side.
    }
  }
  return sampleRows(roleState, limit);
}

// The mapping-sheet payload sent to both the contract compiler
// (/contracts/compile) and the script generator (/transformations/generate):
// the parsed worksheet payload when one was uploaded (sent whole so either
// compiler sees the full business context), otherwise rows built from the
// confirmed field mapping.
export function buildMappingSheetPayload(parsedMappingSheet, mapping) {
  if (parsedMappingSheet?.rows?.length) return parsedMappingSheet;
  return (mapping?.display ?? [])
    .filter((row) => row.source_col && row.target_col)
    .map((row) => ({
      source_field: row.source_col,
      target_field: row.target_col,
      role: /key/i.test(String(row.role)) ? "key" : "compare",
    }));
}

export function hasMappingPayload(payload) {
  return Array.isArray(payload) ? payload.length > 0 : Boolean(payload?.rows?.length);
}

export function isKeyRole(role) {
  return /key/i.test(String(role));
}

// A row the user owns (added or edited): it always wins over anything the LLM
// would generate for the same column, and Regenerate never overwrites it.
export function isUserRow(row) {
  return row?.provenance === "user-edited" || row?.provenance === "user-added";
}

// Merges a freshly-inferred field mapping into the current one, PRESERVING the
// rows the user owns. On "Regenerate", rows flagged `user-edited` / `user-added`
// are kept verbatim; only untouched `"generated"` rows are refreshed from the
// new inference (matched by source_col, in place). A newly inferred row is
// dropped if a preserved user row already claims its source or target column, so
// the mapping stays 1:1. Brand-new inferred rows are appended.
export function mergeGeneratedMapping(prevDisplay, nextDisplay) {
  const prev = prevDisplay ?? [];
  const next = nextDisplay ?? [];
  const userRows = prev.filter(isUserRow);
  const claimedSrc = new Set(userRows.map((r) => r.source_col).filter(Boolean));
  const claimedTgt = new Set(userRows.map((r) => r.target_col).filter(Boolean));

  // Inferred rows that don't collide with a preserved user row, keyed by source_col.
  const nextBySrc = new Map();
  for (const row of next) {
    if (claimedSrc.has(row.source_col)) continue;
    if (row.target_col && claimedTgt.has(row.target_col)) continue;
    if (!nextBySrc.has(row.source_col)) nextBySrc.set(row.source_col, row);
  }

  const merged = [];
  const usedNext = new Set();
  for (const row of prev) {
    if (isUserRow(row)) {
      merged.push(row); // keep the user's row
    } else if (nextBySrc.has(row.source_col)) {
      merged.push(nextBySrc.get(row.source_col)); // refresh generated row in place
      usedNext.add(row.source_col);
    }
    // else: a generated row the new inference no longer proposes is dropped
  }
  for (const [src, row] of nextBySrc) {
    if (!usedNext.has(src)) merged.push(row); // brand-new inferred rows
  }
  return merged;
}

// Rebuilds the backend `mapping` object (key_fields / compare_fields) from the
// current, possibly hand-edited or filtered, display rows so /reconcile stays
// in sync with what the analyst sees.
export function rebuildMapping(display, options) {
  const key_fields = [];
  const compare_fields = [];
  for (const row of display) {
    // Skip incomplete rows (e.g. a freshly-added row the user hasn't finished
    // filling in) — an unpaired half-row is not a mapping.
    if (!row.source_col || !row.target_col) continue;
    const pair = { source_col: row.source_col, target_col: row.target_col };
    if (isKeyRole(row.role)) key_fields.push(pair);
    else compare_fields.push(pair);
  }
  return { key_fields, compare_fields, options: options ?? { case_insensitive: true, trim_whitespace: true } };
}

// Field options for the Business Rules Builder's dropdowns: distinct field
// names drawn from the source schema, the target schema, and (when a mapping
// sheet was uploaded) its inferred mapping candidates — de-duplicated, with a
// business-friendly label preferred over a bare technical name when the
// mapping sheet supplies one for the same field. Order: mapping-sheet
// candidates first (most business-relevant), then any remaining raw schema
// columns, alphabetically.
export function buildRuleFieldOptions(source, target, parsedMappingSheet) {
  const labelByValue = new Map();
  const add = (value, label) => {
    if (!value) return;
    if (!labelByValue.has(value)) labelByValue.set(value, label || value);
  };

  (parsedMappingSheet?.mapping_candidates ?? []).forEach((candidate) => {
    add(candidate.source_field, candidate.source_field);
    add(candidate.technical_field, candidate.target_field || candidate.technical_field);
    add(candidate.target_field, candidate.target_field);
  });
  (source?.dataset?.columns ?? []).forEach((col) => add(col, col));
  (target?.dataset?.columns ?? []).forEach((col) => add(col, col));

  return Array.from(labelByValue.entries())
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

// Trims whitespace and drops incomplete rows (missing field or instruction)
// before a rule list is sent to the backend — mirrors the backend's own
// normalize_business_rules() so nothing incomplete reaches the compiler, and
// rule ordering is preserved.
export function cleanBusinessRules(rules) {
  return (rules ?? [])
    .map((rule) => ({
      field: (rule.field ?? "").trim(),
      instruction: (rule.instruction ?? "").trim(),
    }))
    .filter((rule) => rule.field && rule.instruction);
}

// Maps the UI's { field, aggregation } rows to the contract compiler's
// { source_field, aggregation } shape, dropping incomplete rows and preserving
// order. The backend resolves source_field against the real source schema.
export function cleanAggregationRules(rules) {
  return (rules ?? [])
    .map((rule) => ({
      source_field: (rule.field ?? "").trim(),
      aggregation: (rule.aggregation ?? "").trim(),
    }))
    .filter((rule) => rule.source_field && rule.aggregation);
}
