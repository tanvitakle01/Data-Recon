// The connector catalog the wizard offers, shared by the connector step (which
// renders the grid / Live-Fetch choice) and Step 1 (which needs to know WHICH
// live connector a side will use before one has been picked, so its entity/join
// input can be resolved against that connector's live entity list).
//
// `roles` declares which side(s) a connector is available for. Excel is
// available for both; S/4HANA is a source system, IBP is a target system.
// Anything with an empty `roles` renders as "Coming soon".
export const CONNECTOR_OPTIONS = [
  { id: "excel_upload", label: "Excel Upload", category: "File", kind: "excel", roles: ["source", "target"] },
  { id: "csv_upload", label: "CSV Upload", category: "File", kind: "csv", roles: [] },
  { id: "sap_s4hana", label: "SAP S/4HANA", category: "SAP", kind: "s4", roles: ["source"] },
  { id: "sap_ecc", label: "SAP ECC", category: "SAP", kind: "ecc", roles: [] },
  { id: "sap_bw", label: "SAP BW", category: "SAP", kind: "bw", roles: [] },
  { id: "sap_ibp", label: "SAP IBP", category: "SAP", kind: "ibp", roles: ["target"] },
  { id: "custom", label: "Custom Connector", category: "Custom", kind: "custom", roles: [] },
];

export const EXCEL_OPTION = CONNECTOR_OPTIONS.find((o) => o.id === "excel_upload");

// The single configured Live-Fetch (SAP) connector for a given role. S/4HANA is
// the only source system, IBP the only target — so Live Fetch resolves
// deterministically per role even when no mapping sheet was uploaded.
export function liveFetchOptionFor(role) {
  return CONNECTOR_OPTIONS.find(
    (o) => o.category === "SAP" && o.roles.includes(role) && (o.kind === "s4" || o.kind === "ibp")
  );
}

// The connector `kind` a side's entity/join input should be resolved against:
// whatever the mapping sheet identified for that side if it's a live connector,
// otherwise that role's sole live connector. Returns null when neither applies
// (e.g. the side is a file upload), which callers treat as "no entity input" —
// entities only exist for live connectors.
export function liveKindForRole(role, identifiedSide) {
  const identified = identifiedSide?.kind;
  if (identified === "s4" || identified === "ibp") {
    const opt = CONNECTOR_OPTIONS.find((o) => o.kind === identified);
    if (opt?.roles.includes(role)) return identified;
  }
  return liveFetchOptionFor(role)?.kind ?? null;
}
