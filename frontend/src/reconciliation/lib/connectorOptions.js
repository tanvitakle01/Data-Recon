// Stage 1 supports file upload only — no live connectors — so this is a
// single-entry catalog kept as a module so ConnectorSelectionStep has one
// place to read the Excel connector's id/kind from.
export const CONNECTOR_OPTIONS = [
  { id: "excel_upload", label: "Excel Upload", category: "File", kind: "excel", roles: ["source", "target"] },
];

export const EXCEL_OPTION = CONNECTOR_OPTIONS[0];
