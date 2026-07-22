/* Realistic demo data mirroring the S/4HANA -> IBP reconciliation domain.
   Identifiers here are technical (mono); logical names / evidence are human. */

export const TARGET_FIELD_OPTIONS = [
  "PRDID", "LOCID", "PERIODID0_TSTAMP", "SALESORDERREQUEST",
  "PRODDESC", "PRODGROUP", "LOCNAME", "LOCATIONTYPE", "KEYFIGUREDATE",
];

export const DEFAULT_MAPPING = [
  { logical: "Material", source: "Material", target: "PRDID", type: "key" },
  { logical: "Production Plant", source: "ProductionPlant", target: "LOCID", type: "key" },
  { logical: "Requested Delivery Date", source: "RequestedDeliveryDate", target: "PERIODID0_TSTAMP", type: "key" },
  { logical: "Requested Quantity", source: "RequestedQuantity", target: "SALESORDERREQUEST", type: "compare" },
];

export const PRODUCT_TIER_COUNTS = { very_high: 812, high: 164, medium: 47, none: 23, out_of_scope: 18 };
export const LOCATION_TIER_COUNTS = { very_high: 41, high: 6, medium: 3, none: 2, out_of_scope: 4 };

export const VALUE_MAPPINGS = [
  { src: "000000004711", tgt: "PRD-4711", tier: "very_high", rule: "product.rule2_exact_id", evidence: "Exact identifier match after leading-zero strip." },
  { src: "000000008120", tgt: "PRD-8120", tier: "very_high", rule: "product.rule2_exact_id", evidence: "Exact identifier match." },
  { src: "MAT-COAT-02", tgt: "PRD-COAT2", tier: "high", rule: "product.rule3_normalized_identity", evidence: "Normalized identity match (separators removed)." },
  { src: "GEARBOX-STD", tgt: "PRD-GBX-STD", tier: "high", rule: "product.rule4_alternate_id", evidence: "Matched via alternate id PRDIDDEM." },
  { src: "HOUSING-AL", tgt: "PRD-HOUS-AL", tier: "medium", rule: "product.rule5_description_match", evidence: "Description similarity 0.71 on PRODDESC." },
  { src: "0000LEGACY99", tgt: "—", tier: "none", rule: "product.rule6_no_match", evidence: "No candidate above threshold." },
  { src: "SAMPLE-KIT-X", tgt: "n/a", tier: "out_of_scope", rule: "product.rule0_group_out_of_scope", evidence: "PRODGROUP flagged out of scope." },
];

export const SHADOW_COLUMNS = [
  { key: "material", header: "Material", mono: true },
  { key: "plant", header: "ProductionPlant", mono: true },
  { key: "date", header: "RequestedDeliveryDate", mono: true },
  { key: "qty", header: "RequestedQuantity", mono: true, align: "right" },
];

// each row: before values + after values + per-column change kind
export const SHADOW_ROWS = [
  {
    before: { material: "000000004711", plant: "1010", date: "2026-03-14", qty: "620" },
    after: { material: "4711", plant: "LOC-1010", date: "2026-03", qty: "1,240" },
    changes: { material: "modified", plant: "modified", date: "modified", qty: "aggregated" },
  },
  {
    before: { material: "000000008120", plant: "1010", date: "2026-03-22", qty: "860" },
    after: { material: "8120", plant: "LOC-1010", date: "2026-03", qty: "860" },
    changes: { material: "modified", plant: "modified", date: "modified" },
  },
  {
    before: { material: "MAT-COAT-02", plant: "2020", date: "2026-04-02", qty: "45" },
    after: { material: "MAT-COAT-02", plant: "LOC-2020", date: "2026-04", qty: "45" },
    changes: { plant: "modified", date: "modified" },
  },
  {
    before: { material: "0000LEGACY99", plant: "2020", date: "2026-04-09", qty: "12" },
    after: { material: "—", plant: "LOC-2020", date: "2026-04", qty: "12" },
    changes: { material: "removed", plant: "modified", date: "modified" },
  },
];

/* ---- Results ------------------------------------------------------------- */
export const RESULTS = { matches: 8642, mismatches: 214, missingSource: 96, missingTarget: 148, total: 9100 };

export const RESULT_ROWS = [
  { key: "4711 · LOC-1010 · 2026-03", src: 1240, tgt: 1240, delta: 0, outcome: "match" },
  { key: "8120 · LOC-1010 · 2026-03", src: 860, tgt: 900, delta: 40, outcome: "mismatch" },
  { key: "COAT2 · LOC-2020 · 2026-04", src: 45, tgt: 45, delta: 0, outcome: "match" },
  { key: "GBX-STD · LOC-1010 · 2026-03", src: 0, tgt: 320, delta: 320, outcome: "missing_in_source" },
  { key: "HOUS-AL · LOC-2020 · 2026-04", src: 210, tgt: 0, delta: -210, outcome: "missing_in_target" },
  { key: "4711 · LOC-3030 · 2026-05", src: 512, tgt: 512, delta: 0, outcome: "match" },
];

/* ---- Auxiliary / MDT knowledge (browse by connector) -------------------- */
export const MDT_GROUPS = [
  {
    key: "ibp_product", label: "Target · Product", system: "SAP IBP", root: "PRDID",
    rows: [
      { attr: "PRODDESC", tier: "very_high", status: "confirmed", fill: 98, rule: "used" },
      { attr: "PRODGROUP", tier: "high", status: "confirmed", fill: 92, rule: "used" },
      { attr: "PRDIDDEM", tier: "high", status: "confirmed", fill: 74, rule: "used" },
      { attr: "PRODTYPE", tier: "medium", status: "empty", fill: 0, rule: "exists" },
      { attr: "SPRODDESC", tier: "medium", status: "absent", fill: null, rule: "recommended" },
    ],
  },
  {
    key: "ibp_location", label: "Target · Location", system: "SAP IBP", root: "LOCID",
    rows: [
      { attr: "LOCNAME", tier: "very_high", status: "confirmed", fill: 100, rule: "used" },
      { attr: "LOCATIONTYPE", tier: "high", status: "confirmed", fill: 88, rule: "used" },
      { attr: "LOCCOUNTRY", tier: "medium", status: "confirmed", fill: 63, rule: "exists" },
      { attr: "LOCIDDEM", tier: "medium", status: "empty", fill: 0, rule: "recommended" },
    ],
  },
  {
    key: "s4_product", label: "Source · Product", system: "SAP S/4HANA", root: "Material",
    rows: [
      { attr: "SalesOrderItemText", tier: "high", status: "confirmed", fill: 81, rule: "used" },
      { attr: "MaterialGroup", tier: "high", status: "confirmed", fill: 95, rule: "used" },
      { attr: "MaterialPricingGroup", tier: "medium", status: "empty", fill: 0, rule: "exists" },
      { attr: "AdditionalMaterialGroup1", tier: "medium", status: "absent", fill: null, rule: "recommended" },
    ],
  },
  {
    key: "s4_plant", label: "Source · Plant", system: "SAP S/4HANA", root: "ProductionPlant",
    rows: [
      { attr: "OriginalPlant", tier: "high", status: "confirmed", fill: 70, rule: "used" },
    ],
  },
];

export const AUX_STATUS = {
  confirmed: { status: "match", label: "Confirmed" },
  empty: { status: "medium", label: "Empty (0% filled)" },
  absent: { status: "missing", label: "Absent" },
};
export const AUX_RULE = {
  used: { status: "match", label: "Yes — evidence input" },
  exists: { status: "medium", label: "Rule exists, not populated" },
  recommended: { status: "scope", label: "Recommended (no rule yet)" },
};

/* ---- Dashboard ----------------------------------------------------------- */
export const RECENT_RUNS = [
  { id: "contract_a1b2c3d4e5f6", type: "Sales Order History", pair: "S/4HANA → IBP", match: 95.0, exceptions: 458, when: "2h ago", status: "match" },
  { id: "contract_9f8e7d6c5b4a", type: "Sales Order History", pair: "S/4HANA → IBP", match: 88.4, exceptions: 1120, when: "Yesterday", status: "medium" },
  { id: "contract_1122334455aa", type: "Sales Order History", pair: "S/4HANA → IBP", match: 99.1, exceptions: 84, when: "2 days ago", status: "match" },
  { id: "contract_aabbccddeeff", type: "Sales Order History", pair: "S/4HANA → IBP", match: 72.6, exceptions: 2490, when: "4 days ago", status: "missing" },
];

export const MATCH_TREND = [
  { label: "Mon", value: 91 }, { label: "Tue", value: 88 }, { label: "Wed", value: 94 },
  { label: "Thu", value: 90 }, { label: "Fri", value: 96 }, { label: "Sat", value: 93 }, { label: "Sun", value: 95 },
];
