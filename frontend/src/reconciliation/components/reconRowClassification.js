// Row-level `classification` (from the detail frame) -> Canopy Badge variant
// — distinct from the summary buckets used elsewhere, which fold
// missing_in_source/missing_in_target into one "mismatch" count. Shared by
// ContractRunResults and StoredRunsPage so both surfaces label a row the
// same way.
export const ROW_CLASS = {
  match: { label: "Match", variant: "success" },
  mismatch: { label: "Quantity mismatch", variant: "error" },
  missing_in_target: { label: "Missing in target", variant: "warning" },
  missing_in_source: { label: "Missing in source", variant: "warning" },
};
