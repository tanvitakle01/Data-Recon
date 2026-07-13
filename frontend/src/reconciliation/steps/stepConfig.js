export const WIZARD_STEPS = [
  {
    key: "comparisonType",
    path: "comparison-type",
    number: 1,
    label: "Type",
    description: "Choose the business process being reconciled.",
  },
  {
    key: "source",
    path: "source",
    number: 2,
    label: "Source",
    description: "Connect to or upload the source dataset.",
  },
  {
    key: "target",
    path: "target",
    number: 3,
    label: "Target",
    description: "Connect to or upload the target dataset.",
  },
  {
    key: "transformationSpec",
    path: "transformation-spec",
    number: 4,
    label: "Rules",
    description:
      "Attach transformation documents, add rules, and confirm the source-to-target field mapping.",
  },
  {
    key: "reviewChanges",
    path: "review-changes",
    number: 5,
    label: "Review",
    description:
      "Inspect the transformed shadow source against the original and the target, then approve it before reconciling.",
    // Only meaningful for the contract engine, which derives a Shadow_Source
    // from the approved contract's operations. The script engine already
    // approves transformed data in the Transformation Spec step.
    contractOnly: true,
  },
  {
    key: "reconciliation",
    path: "reconciliation",
    number: 6,
    label: "Results",
    description: "Run the comparison, review the results, and open insights.",
  },
];

// The steps actually shown for the current engine. The Review Changes step is
// hidden when the script-transformation flow is active (useScriptTransformations
// === true); it stays visible for the contract engine (false) and while the
// mode is still being fetched (null), so the default/primary path shows it.
export function getVisibleSteps(useScriptTransformations) {
  if (useScriptTransformations === true) {
    return WIZARD_STEPS.filter((step) => !step.contractOnly);
  }
  return WIZARD_STEPS;
}

export function getStepByKey(key) {
  return WIZARD_STEPS.find((step) => step.key === key) ?? null;
}

export function getStepIndex(key) {
  return WIZARD_STEPS.findIndex((step) => step.key === key);
}
