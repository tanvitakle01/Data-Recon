// Appends one reconciliation side (source or target) to a FormData in the
// shape /automap and /reconcile expect: an uploaded Excel file
// (`<role>_file` + optional `sheet_name_<role>`) for Excel datasets, or a
// JSON `<role>_rows` array for SAP-fetched datasets. Returns true if data
// was appended, false if the side has no usable payload (e.g. after a
// refresh dropped the in-memory file/rows).
//
// `excludeFields` (optional) drops those columns from the JSON rows before
// sending — used by the field-mapping inference (/api/recon/mapping/infer) to
// keep MDT/recommended columns out of the inference entirely (see runInference
// in TransformationSpecStep) without touching the dataset used for reconciliation.
export function appendDatasetSide(formData, role, roleState, excludeFields) {
  const dataset = roleState?.dataset;
  if (!dataset) return false;

  if (roleState.kind === "excel" && dataset.file) {
    formData.append(`${role}_file`, dataset.file);
    if (dataset.sheet) formData.append(`sheet_name_${role}`, dataset.sheet);
    return true;
  }

  if (Array.isArray(dataset.rows) && dataset.rows.length > 0) {
    const rows = excludeFields?.length ? omitFields(dataset.rows, excludeFields) : dataset.rows;
    formData.append(`${role}_rows`, JSON.stringify(rows));
    return true;
  }

  return false;
}

// FormData for POST /api/recon/value-mapping/run: the full current source +
// target datasets (no field exclusions — the matchers read columns, e.g.
// MaterialGroup/PRODGROUP, that aren't part of the confirmed field mapping at
// all), in the same file-or-rows shape /automap and /reconcile use. Returns
// null if either side has no usable payload (e.g. after a refresh dropped the
// in-memory file/rows).
export function buildValueMappingFormData(source, target) {
  const formData = new FormData();
  const okSource = appendDatasetSide(formData, "source", source);
  const okTarget = appendDatasetSide(formData, "target", target);
  return okSource && okTarget ? formData : null;
}

// The field-mapping rows required before "Run Deterministic Mapping" can
// fire: each names the source field, the required target field, and whether
// it must be confirmed as a Key or Compare mapping.
export const REQUIRED_VALUE_MAPPING_FIELDS = [
  { source: "Material", target: "PRDID", role: "key" },
  { source: "ProductionPlant", target: "LOCID", role: "key" },
  { source: "RequestedDeliveryDate", target: "PERIODID0_TSTAMP", role: "key" },
  { source: "RequestedQuantity", target: "SALESORDERREQUEST", role: "compare" },
];

// Which of the rows above are still missing/unconfirmed in the current field
// mapping — surfaced on the button's disabled tooltip so the user knows
// exactly what to fix, rather than letting it fire against an incomplete map.
export function missingValueMappingRequirements(display) {
  const rows = display ?? [];
  return REQUIRED_VALUE_MAPPING_FIELDS.filter(
    (req) =>
      !rows.some((row) => {
        if (row.source_col !== req.source || row.target_col !== req.target) return false;
        return req.role === "key" ? isKeyRole(row.role) : !isKeyRole(row.role);
      }),
  );
}

function omitFields(rows, fields) {
  const drop = new Set(fields);
  return rows.map((row) => {
    const next = {};
    for (const key of Object.keys(row)) {
      if (!drop.has(key)) next[key] = row[key];
    }
    return next;
  });
}

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
