// Entity model for the Mapping Review workspace. Generalizes the deterministic
// value-mapping run (currently Product + Location) into a list of business
// "mapping entities", each rendered as one accordion card on the review page.
//
// New entities (Customer → Customer, Vendor → Supplier, …) only need a config
// entry in MAPPING_ENTITY_CONFIG — the page renders whatever entities are
// actually present in the run payload, so no page/component change is required
// to light up a new entity once the backend returns it.
//
// This module is also the seam for future MDT Library integration: each built
// entity object is the single place where approved mappings, MDT fields,
// evidence rules, confidence history, and user approvals will hang off (see the
// `mdt` placeholder below). Keeping that shape here means the cards never have
// to change when the library lands — only this builder grows.

export const TIER_LABEL = {
  very_high: "VERY_HIGH",
  high: "HIGH",
  medium: "MEDIUM",
  none: "NONE",
  out_of_scope: "OUT_OF_SCOPE",
};

// Order used for the header stat chips and the tier summary strip.
export const TIER_ORDER = ["very_high", "high", "medium", "none", "out_of_scope"];

// Tiers that count as a real, usable match (mapped, in-scope).
const MAPPED_TIERS = ["very_high", "high", "medium"];

// Filter tabs shown inside an expanded entity card. `tier: null` = show all.
export const ENTITY_FILTERS = [
  { id: "all", label: "All", tier: null },
  { id: "very_high", label: "Very High", tier: "very_high" },
  { id: "high", label: "High", tier: "high" },
  { id: "medium", label: "Medium", tier: "medium" },
  { id: "none", label: "Unmapped", tier: "none" },
  { id: "out_of_scope", label: "Excluded", tier: "out_of_scope" },
];

// Per-entity display + wiring. `key` matches the valueMappings payload key and
// `auxGroups` matches the auxiliary_fields payload keys the backend returns.
// `defaultExpanded` seeds the "only Material/Product open by default" rule.
export const MAPPING_ENTITY_CONFIG = [
  {
    key: "product",
    entity: "Product",
    sourceEntity: "Material",
    targetEntity: "Product",
    auxGroups: ["source_product", "target_product"],
    defaultExpanded: true,
  },
  {
    key: "location",
    entity: "Location",
    sourceEntity: "ProductionPlant",
    targetEntity: "Location",
    auxGroups: ["source_plant", "target_location"],
    defaultExpanded: false,
  },
  // Future entities plug in here — e.g.
  // { key: "customer", entity: "Customer", sourceEntity: "Customer",
  //   targetEntity: "Customer", auxGroups: [...], defaultExpanded: false },
  // { key: "vendor", entity: "Supplier", sourceEntity: "Vendor",
  //   targetEntity: "Supplier", auxGroups: [...], defaultExpanded: false },
];

export const AUX_GROUP_LABEL = {
  target_product: "Target · Product (IBP)",
  target_location: "Target · Location (IBP)",
  source_product: "Source · Product (S/4)",
  source_plant: "Source · Plant (S/4)",
};

export function tierCounts(matches) {
  const counts = { very_high: 0, high: 0, medium: 0, none: 0, out_of_scope: 0 };
  for (const m of matches ?? []) {
    if (counts[m.confidence] !== undefined) counts[m.confidence] += 1;
  }
  return counts;
}

// Review-readiness signal for the summary's "Approval status" column. This page
// is read-only — no approval action lives here (the human gate is the Run
// Reconciliation confirmation) — so this is *readiness*, not a stored approval.
// It's exactly the field the future MDT approval workflow will replace with a
// real approved / pending / rejected state persisted on `entity.mdt`.
export function reviewStatus({ mapped, unmapped }) {
  if (mapped === 0) return { key: "none", label: "No matches", variant: "error" };
  if (unmapped > 0) return { key: "gaps", label: "Review gaps", variant: "warning" };
  return { key: "ready", label: "Ready to approve", variant: "teal" };
}

// Turn the raw /value-mapping/run payload into the accordion's entity list.
// Only entities actually present in the payload are returned, in config order.
export function buildMappingEntities(valueMappings) {
  if (!valueMappings) return [];
  const aux = valueMappings.auxiliaryFields ?? {};

  return MAPPING_ENTITY_CONFIG.filter((cfg) => valueMappings[cfg.key]).map((cfg) => {
    const mapping = valueMappings[cfg.key];
    const matches = mapping.matches ?? [];
    const counts = tierCounts(matches);
    const total = matches.length;
    const mapped = MAPPED_TIERS.reduce((n, tier) => n + counts[tier], 0);
    const excluded = counts.out_of_scope;
    const inScope = total - excluded;
    const unmapped = counts.none;
    // Coverage is measured against in-scope values only: excluded-from-scope
    // values are deliberately not reconciled, so they neither help nor hurt.
    const coverage = inScope > 0 ? mapped / inScope : 0;

    const auxFields = cfg.auxGroups.flatMap((group) =>
      (aux[group] ?? []).map((field) => ({ ...field, group }))
    );

    return {
      ...cfg,
      mapping,
      matches,
      counts,
      total,
      mapped,
      excluded,
      inScope,
      unmapped,
      coverage,
      auxFields,
      status: reviewStatus({ mapped, unmapped }),
      // Reserved for future MDT Library integration. Today the deterministic run
      // is the only source of truth; when the library lands, these fields get
      // populated here and the cards render them without structural changes:
      //   approvedMappings, mdtFields, evidenceRules, confidenceHistory,
      //   userApprovals.
      mdt: null,
    };
  });
}
