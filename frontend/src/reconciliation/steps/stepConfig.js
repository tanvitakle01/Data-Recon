export const WIZARD_STEPS = [
  {
    key: "comparisonType",
    path: "comparison-type",
    number: 1,
    label: "Dataset Type",
    description: "Choose the dataset being reconciled.",
  },
  {
    key: "source",
    path: "source",
    number: 2,
    label: "Source",
    description: "Upload the source dataset.",
  },
  {
    key: "target",
    path: "target",
    number: 3,
    label: "Target",
    description: "Upload the target dataset.",
  },
  {
    key: "transformationSpec",
    path: "transformation-spec",
    number: 4,
    label: "Mapping",
    description:
      "Choose Manual or Deterministic mapping and prepare the data for reconciliation.",
  },
  {
    key: "reconciliation",
    path: "reconciliation",
    number: 5,
    label: "Results",
    description: "Run the comparison and review the results.",
  },
];

// The steps actually shown for the current engine. Both the Manual and
// Deterministic mapping flows now complete inside the single Mapping step
// (shadow preview/approval is embedded there for Manual; the Deterministic
// path confirms at Run time), so every engine shows the same five numbered
// steps. Kept as a function because the stepper/StepShell call it to derive
// position; it currently returns all steps for every engine.
export function getVisibleSteps() {
  return WIZARD_STEPS;
}

export function getStepByKey(key) {
  return WIZARD_STEPS.find((step) => step.key === key) ?? null;
}

export function getStepIndex(key) {
  return WIZARD_STEPS.findIndex((step) => step.key === key);
}
