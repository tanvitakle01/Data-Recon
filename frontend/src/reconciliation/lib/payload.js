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
