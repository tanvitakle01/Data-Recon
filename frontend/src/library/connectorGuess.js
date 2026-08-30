// Cosmetic-only relabeling for the Mapping Library table.
//
// The literal "upload" connector value only ever comes from the chat/quick-
// reconcile flow (backend/routes/auto_pipeline.py), which compares two raw
// files with no mapping sheet and no system-identification step — there is no
// sheet evidence saying which SAP system either file represents. Everywhere
// else in the app, an uploaded file is stored as "excel" (see
// reconciliation/lib/connectorOptions.js), never "upload".
//
// This module never changes what a run fetched or what got persisted — it
// only decides, from the field names a stored mapping already has, whether
// there's a strong enough naming-convention signal (mirroring the cues
// backend/recon_engine/sheet_identifier.py uses for real identification) to
// show a friendlier label than "upload" in the library. No signal, no guess —
// the raw value is left exactly as it is, same discipline the backend applies
// to real connector identification.

const S4_TABLE_FIELD_RE = /^[A-Z][A-Z0-9]*-[A-Z0-9_]+$/; // e.g. VBAP-MATNR, VBEP-EDATU
const BW_INFO_OBJECT_RE = /^0[A-Z][A-Z0-9_]*$/; // e.g. 0MATERIAL, 0PLANT, 0CALDAY
const IBP_FIELD_NAMES = new Set(["PRDID", "LOCID", "SALESORDERREQUEST", "PERIODID0_TSTAMP", "PERIODID0"]);

const CONNECTOR_LABELS = { s4: "SAP S/4HANA", ibp: "SAP IBP", bw: "SAP BW" };

function guessKind(fieldNames) {
  const names = (fieldNames || []).map((n) => String(n || "").trim()).filter(Boolean);
  if (names.some((n) => S4_TABLE_FIELD_RE.test(n))) return "s4";
  if (names.some((n) => IBP_FIELD_NAMES.has(n.toUpperCase()))) return "ibp";
  if (names.some((n) => BW_INFO_OBJECT_RE.test(n))) return "bw";
  return null;
}

// Returns { label, inferred }. `inferred: true` means the label was guessed
// from field names, not the value actually stored — callers should mark it
// as such (e.g. a tooltip) rather than presenting it as confirmed fact.
export function resolveUploadConnector(rawValue, fieldNames) {
  if (rawValue !== "upload") return { label: rawValue, inferred: false };
  const kind = guessKind(fieldNames);
  return kind ? { label: CONNECTOR_LABELS[kind], inferred: true } : { label: rawValue, inferred: false };
}
