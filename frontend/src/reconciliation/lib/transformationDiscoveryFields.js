// Field-selection rules for Transformation Discovery (SAP <-> IBP mapping of
// Material -> PRDID and ProductionPlant -> LOCID). When a user checks one of
// these trigger fields in a dataset workspace's column picker, the listed
// supporting attributes are auto-checked alongside it so the user doesn't
// have to hunt down every field the mapping needs by hand.

// The supporting attributes mirror the Tier-1/Tier-2 auxiliary seed lists in
// backend/recon_engine/matching/auxiliary.py (TARGET_PRODUCT_SEEDS /
// TARGET_LOCATION_SEEDS / SOURCE_PRODUCT_SEEDS / SOURCE_PLANT_SEEDS). Keeping
// them in sync means every candidate the recommender evaluates is actually
// fetched, so its "Recommended for Deterministic Mapping" panel shows a real
// fill rate instead of "Absent". Names that don't exist on a given entity are
// dropped silently by recommendedFieldsFor.
export const IBP_TRANSFORMATION_DISCOVERY_FIELDS = {
  PRDID: [
    "PRDID", "PRODDESC", "PRODDESCDEM", "PRODGROUP", "PRODTYPE", "PRDIDDEM",
    "PRODGROUPDEM", "PRODTYPEDEM", "SPRDID", "SPRODDESC", "SPRODGROUP",
    "SPRODTYPE",
  ],
  LOCID: [
    "LOCID", "LOCNAME", "LOCDESCRDEM", "LOCATIONTYPE", "LOCTYPEDEM",
    "LOCCOUNTRY", "LOCIDDEM", "LOCATIONREGION", "LOCCITY", "LOCTIMEZONE",
    "SOURCELOCATIONTZ",
  ],
};

export const S4_TRANSFORMATION_DISCOVERY_FIELDS = {
  Material: [
    "Material",
    "SalesOrderItemText",
    "MaterialGroup",
    "MaterialPricingGroup",
    "AdditionalMaterialGroup1",
    "AdditionalMaterialGroup2",
    "AdditionalMaterialGroup3",
    "AdditionalMaterialGroup4",
    "AdditionalMaterialGroup5",
  ],
  ProductionPlant: ["ProductionPlant", "OriginalPlant"],
};

// Returns the rule's supporting fields that actually exist in the dataset
// (or joined entity), silently dropping any that don't — a partial schema
// never blocks selection or raises an error. Returns [] if `triggerField`
// isn't a rule trigger.
export function recommendedFieldsFor(rules, triggerField, availableFieldNames) {
  const recommended = rules[triggerField];
  if (!recommended) return [];
  const available = new Set(availableFieldNames);
  return recommended.filter((f) => available.has(f));
}

// Widen a base column selection with the supporting auxiliary fields of every
// trigger field it already contains (filtered to fields that actually exist).
// Returns the widened selection plus the SET of fields that were auto-added, so
// the caller can track them as MDT/recommended evidence fields — fetched and
// fed to the deterministic matcher, but excluded from the field mapping. A
// field already in `baseSelection` is never reported as auto-added.
export function withAuxiliaryFields(rules, baseSelection, availableFieldNames) {
  const selection = new Set(baseSelection);
  const autoAdded = new Set();
  for (const trigger of baseSelection) {
    for (const f of recommendedFieldsFor(rules, trigger, availableFieldNames)) {
      if (!selection.has(f)) {
        selection.add(f);
        autoAdded.add(f);
      }
    }
  }
  return { selection: Array.from(selection), autoAdded };
}
