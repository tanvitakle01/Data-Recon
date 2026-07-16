// Field-selection rules for Transformation Discovery (SAP <-> IBP mapping of
// Material -> PRDID and ProductionPlant -> LOCID). When a user checks one of
// these trigger fields in a dataset workspace's column picker, the listed
// supporting attributes are auto-checked alongside it so the user doesn't
// have to hunt down every field the mapping needs by hand.

export const IBP_TRANSFORMATION_DISCOVERY_FIELDS = {
  PRDID: ["PRDID", "PRODDESC", "PRODTYPE", "PRODGROUP", "PRDIDDEM", "SPRDID", "SPRODDESC"],
  LOCID: ["LOCID", "LOCNAME", "LOCDESCRDEM", "LOCATIONTYPE", "LOCTYPEDEM", "LOCCOUNTRY", "LOCATIONREGION"],
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
