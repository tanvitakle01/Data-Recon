// Deterministic validation of LLM-proposed sheet fields against a live schema.
//
// The sheet-driven identifier proposes field names copied verbatim from the
// mapping sheet (e.g. "PRDID", or S/4 "VBAP-MATNR" TABLE-FIELD forms). Before
// anything is pre-selected we intersect those proposals with the REAL columns
// the connector exposes — a proposal that doesn't exist in the live schema is
// never selected, only surfaced so the human can locate it by hand. This is
// the "LLM proposes, schema validates" contract: no invented fields.
//
// Matching is normalized (case-insensitive, non-alphanumerics stripped) and
// also tries the trailing TABLE-FIELD segment (VBAP-MATNR → MATNR), which
// bridges some naming conventions. It deliberately does NOT do semantic
// mapping (MATNR → Material) — that lives in the Step 4 compiler; unmatched
// proposals are reported, not guessed.

function normalize(value) {
  return String(value ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

// Candidate normalized keys for one proposed field: the whole string plus the
// segment after the last '-', '/', or '.' (TABLE-FIELD / path forms).
function candidateKeys(proposed) {
  const keys = new Set();
  const whole = normalize(proposed);
  if (whole) keys.add(whole);
  const segment = String(proposed ?? "").split(/[-/.]/).pop();
  const segKey = normalize(segment);
  if (segKey) keys.add(segKey);
  return keys;
}

// Returns { matched, unmatched }:
//   matched   — real schema names (original casing) the proposals resolve to
//   unmatched — proposals with no live-schema match (surface these to the user)
export function matchProposedToSchema(proposedFields, schemaNames) {
  const index = new Map(); // normalized -> real schema name
  for (const name of schemaNames ?? []) {
    const key = normalize(name);
    if (key && !index.has(key)) index.set(key, name);
  }

  const matched = [];
  const matchedSet = new Set();
  const unmatched = [];
  for (const proposed of proposedFields ?? []) {
    let hit = null;
    for (const key of candidateKeys(proposed)) {
      if (index.has(key)) {
        hit = index.get(key);
        break;
      }
    }
    if (hit) {
      if (!matchedSet.has(hit)) {
        matchedSet.add(hit);
        matched.push(hit);
      }
    } else if (proposed) {
      unmatched.push(proposed);
    }
  }
  return { matched, unmatched };
}
