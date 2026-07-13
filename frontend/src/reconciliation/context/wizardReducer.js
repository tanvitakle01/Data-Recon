import { WIZARD_STEPS, getVisibleSteps } from "../steps/stepConfig";

export const STEP_KEYS = WIZARD_STEPS.map((step) => step.key);

export const WizardActions = {
  SET_CONNECTOR: "SET_CONNECTOR",
  SET_ROLE_STATUS: "SET_ROLE_STATUS",
  SET_DATASET: "SET_DATASET",
  RESET_ROLE: "RESET_ROLE",
  SET_COMPARISON_TYPE: "SET_COMPARISON_TYPE",
  SET_MAPPING_SHEET: "SET_MAPPING_SHEET",
  SET_PARSED_MAPPING_SHEET: "SET_PARSED_MAPPING_SHEET",
  SET_BUSINESS_RULES: "SET_BUSINESS_RULES",
  SET_AGGREGATION_RULES: "SET_AGGREGATION_RULES",
  SET_TRANSFORMATION_MAPPING: "SET_TRANSFORMATION_MAPPING",
  SET_DRAFT_CONTRACT: "SET_DRAFT_CONTRACT",
  SET_CONTRACT_VALIDATION: "SET_CONTRACT_VALIDATION",
  SET_APPROVED_CONTRACT: "SET_APPROVED_CONTRACT",
  SET_SHADOW_SNAPSHOTS: "SET_SHADOW_SNAPSHOTS",
  SET_SHADOW_PREVIEW: "SET_SHADOW_PREVIEW",
  SET_SHADOW_APPROVAL: "SET_SHADOW_APPROVAL",
  SET_SCRIPT_TRANSFORMATIONS_MODE: "SET_SCRIPT_TRANSFORMATIONS_MODE",
  SET_GENERATED_SCRIPT: "SET_GENERATED_SCRIPT",
  SET_SCRIPT_PREVIEW: "SET_SCRIPT_PREVIEW",
  SET_SCRIPT_APPROVAL: "SET_SCRIPT_APPROVAL",
  SET_RECONCILIATION_RESULT: "SET_RECONCILIATION_RESULT",
  GO_TO_STEP: "GO_TO_STEP",
  COMPLETE_STEP: "COMPLETE_STEP",
  RESET_WIZARD: "RESET_WIZARD",
};

function createInitialRoleState() {
  return {
    connectorId: null,
    kind: null, // "excel" | "s4" | "ibp"
    dataset: null, // { columns, preview, rowCount, rows|null, file|null, filename, sheet, sheets, fetchedAt }
    status: "idle", // idle | connecting | ready | error
    error: null,
  };
}

function createInitialTransformationSpec() {
  return {
    mappingSheet: null, // { name, size, file } — optional uploaded mapping sheet
    parsedMappingSheet: null, // /api/recon/mapping-sheet/parse response (structured rows)
    // Structured Business Rules Builder output — replaces the old free-text
    // `rulesText`. Each entry is { field, instruction }.
    transformationRules: [],
    matchingRules: [],
    filterRules: [],
    // Structured aggregation rules ({ field, aggregation }) applied before
    // reconciliation.
    aggregationRules: [],
    mapping: null, // { display: [...], mapping: {...} } from /automap, possibly hand-edited
    draftContract: null, // DraftContract JSON from /api/recon/contracts/compile
    validation: null, // { ok, gate1, gate2 } from /api/recon/contracts/validate
    contract: null, // approved TransformationContract from /api/recon/contracts/approve
    // Review-Changes checkpoint (contract engine). Snapshots are created once
    // here and reused by the run so the reviewed shadow == the reconciled one.
    sourceSnapshotId: null,
    targetSnapshotId: null,
    shadowPreview: null, // /api/recon/shadow-preview response (original/shadow/diffs/target)
    shadowApproved: null, // fingerprint the user approved; gates the run
    // Script-transformation flow (USE_SCRIPT_TRANSFORMATIONS): the user
    // approves transformed DATA, not code. See TransformationPreviewPanel.
    useScriptTransformations: null, // fetched once from /api/recon/transformations/mode
    generatedScript: null, // { script, validation, degraded, degraded_reason }
    scriptPreview: null, // /api/recon/transformations/preview response
    scriptApproval: null, // { approval_id, ... } from /api/recon/transformations/approve
  };
}

export function createInitialWizardState() {
  const stepStatus = {};
  STEP_KEYS.forEach((key, index) => {
    stepStatus[key] = index === 0 ? "available" : "locked"; // locked | available | complete
  });

  return {
    step: STEP_KEYS[0],
    stepStatus,
    source: createInitialRoleState(),
    target: createInitialRoleState(),
    comparisonType: null,
    transformationSpec: createInitialTransformationSpec(),
    reconciliation: null,
  };
}

// The next step to unlock/navigate to, skipping steps hidden for the current
// engine (e.g. Review Changes in the script flow). Falls back to the canonical
// order when the engine mode isn't known yet.
function nextStepKey(state, key) {
  const steps = getVisibleSteps(state?.transformationSpec?.useScriptTransformations);
  const index = steps.findIndex((step) => step.key === key);
  return index >= 0 ? steps[index + 1]?.key ?? null : null;
}

// Whenever a dataset (or connector) changes, any mapping/results derived from
// the *previous* data are stale — a mapping can reference columns that no
// longer exist in the newly loaded file (this is what produced errors like
// "Mapped source key column missing: 'Plant'"). Clear that derived state and
// re-lock the downstream steps so the mapping is recomputed against the fresh
// columns and the comparison is re-run.
function invalidateDerivedState(state) {
  const stepStatus = { ...state.stepStatus };
  // Transformation Spec becomes available again only once the step directly
  // before it is complete. Deriving the predecessor from STEP_KEYS keeps this
  // correct regardless of the wizard's ordering (Comparison Type now leads,
  // with Target as the step immediately preceding Transformation Spec). Because
  // steps unlock sequentially, a complete predecessor implies all earlier
  // steps are complete too.
  const transformIndex = STEP_KEYS.indexOf("transformationSpec");
  const prevKey = STEP_KEYS[transformIndex - 1];
  stepStatus.transformationSpec =
    stepStatus[prevKey] === "complete" ? "available" : "locked";
  // The Review-Changes checkpoint and the run both depend on the (now stale)
  // contract and snapshots — re-lock them so the user re-reviews fresh data.
  stepStatus.reviewChanges = "locked";
  stepStatus.reconciliation = "locked";

  return {
    ...state,
    stepStatus,
    // A contract compiled against the previous schemas is stale too — Gate 1
    // validates field references against the actual dataset columns, so a
    // dataset change invalidates the whole compile→validate→approve chain.
    transformationSpec: {
      ...state.transformationSpec,
      mapping: null,
      draftContract: null,
      validation: null,
      contract: null,
      sourceSnapshotId: null,
      targetSnapshotId: null,
      shadowPreview: null,
      shadowApproved: null,
      generatedScript: null,
      scriptPreview: null,
      scriptApproval: null,
    },
    reconciliation: null,
  };
}

export function wizardReducer(state, action) {
  switch (action.type) {
    case WizardActions.SET_CONNECTOR: {
      const { role, connectorId, kind } = action;
      // Switching connectors discards the old dataset for this role, so any
      // derived mapping/results are stale too.
      return invalidateDerivedState({
        ...state,
        [role]: { ...createInitialRoleState(), connectorId, kind },
      });
    }

    case WizardActions.SET_ROLE_STATUS: {
      const { role, status, error = null } = action;
      return { ...state, [role]: { ...state[role], status, error } };
    }

    case WizardActions.SET_DATASET: {
      const { role, dataset } = action;
      // Fresh data loaded (upload or re-fetch): replace this role's dataset
      // wholesale and clear any stale mapping/results derived from prior data.
      return invalidateDerivedState({
        ...state,
        [role]: { ...state[role], dataset, status: "ready", error: null },
      });
    }

    case WizardActions.RESET_ROLE: {
      const { role } = action;
      return invalidateDerivedState({ ...state, [role]: createInitialRoleState() });
    }

    case WizardActions.SET_COMPARISON_TYPE:
      return { ...state, comparisonType: action.comparisonType };

    case WizardActions.SET_MAPPING_SHEET:
      // A new (or removed) mapping sheet invalidates anything derived from the
      // previous one: parsed rows and the compiled/validated/approved contract
      // (or, in the script flow, the generated script/preview/approval).
      return {
        ...state,
        transformationSpec: {
          ...state.transformationSpec,
          mappingSheet: action.mappingSheet,
          parsedMappingSheet: null,
          draftContract: null,
          validation: null,
          contract: null,
          generatedScript: null,
          scriptPreview: null,
          scriptApproval: null,
        },
      };

    case WizardActions.SET_PARSED_MAPPING_SHEET:
      return {
        ...state,
        transformationSpec: {
          ...state.transformationSpec,
          parsedMappingSheet: action.parsedMappingSheet,
        },
      };

    case WizardActions.SET_BUSINESS_RULES: {
      // `category` is one of "transformationRules" | "matchingRules" | "filterRules".
      const { category, rules } = action;
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, [category]: rules },
      };
    }

    case WizardActions.SET_AGGREGATION_RULES:
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, aggregationRules: action.rules },
      };

    case WizardActions.SET_TRANSFORMATION_MAPPING:
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, mapping: action.mapping },
      };

    case WizardActions.SET_DRAFT_CONTRACT:
      // A fresh draft supersedes any previous validation, approval, and the
      // shadow review derived from it.
      return {
        ...state,
        stepStatus: { ...state.stepStatus, reviewChanges: "locked", reconciliation: "locked" },
        transformationSpec: {
          ...state.transformationSpec,
          draftContract: action.draftContract,
          validation: null,
          contract: null,
          shadowPreview: null,
          shadowApproved: null,
        },
      };

    case WizardActions.SET_CONTRACT_VALIDATION:
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, validation: action.validation },
      };

    case WizardActions.SET_APPROVED_CONTRACT:
      // A (re)approved contract requires a fresh shadow review before running —
      // drop any prior preview/approval and re-lock reconciliation.
      return {
        ...state,
        stepStatus: { ...state.stepStatus, reconciliation: "locked" },
        transformationSpec: {
          ...state.transformationSpec,
          contract: action.contract,
          shadowPreview: null,
          shadowApproved: null,
        },
      };

    case WizardActions.SET_SHADOW_SNAPSHOTS:
      return {
        ...state,
        transformationSpec: {
          ...state.transformationSpec,
          sourceSnapshotId: action.sourceSnapshotId,
          targetSnapshotId: action.targetSnapshotId,
        },
      };

    case WizardActions.SET_SHADOW_PREVIEW:
      // A fresh preview supersedes any previous approval — it must be re-approved.
      return {
        ...state,
        stepStatus: { ...state.stepStatus, reconciliation: "locked" },
        transformationSpec: {
          ...state.transformationSpec,
          shadowPreview: action.shadowPreview,
          shadowApproved: null,
        },
      };

    case WizardActions.SET_SHADOW_APPROVAL:
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, shadowApproved: action.shadowApproved },
      };

    case WizardActions.SET_SCRIPT_TRANSFORMATIONS_MODE:
      return {
        ...state,
        transformationSpec: {
          ...state.transformationSpec,
          useScriptTransformations: action.useScriptTransformations,
        },
      };

    case WizardActions.SET_GENERATED_SCRIPT:
      // A fresh script supersedes any previous preview and approval.
      return {
        ...state,
        transformationSpec: {
          ...state.transformationSpec,
          generatedScript: action.generatedScript,
          scriptPreview: null,
          scriptApproval: null,
        },
      };

    case WizardActions.SET_SCRIPT_PREVIEW:
      // A fresh preview (re-run) supersedes any previous approval — the
      // approval must be re-issued against the current transformed data.
      return {
        ...state,
        transformationSpec: {
          ...state.transformationSpec,
          scriptPreview: action.scriptPreview,
          scriptApproval: null,
        },
      };

    case WizardActions.SET_SCRIPT_APPROVAL:
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, scriptApproval: action.scriptApproval },
      };

    case WizardActions.SET_RECONCILIATION_RESULT:
      return { ...state, reconciliation: action.result };

    case WizardActions.COMPLETE_STEP: {
      const { step } = action;
      const stepStatus = { ...state.stepStatus, [step]: "complete" };
      const next = nextStepKey(state, step);
      if (next && stepStatus[next] === "locked") {
        stepStatus[next] = "available";
      }
      return { ...state, stepStatus };
    }

    case WizardActions.GO_TO_STEP: {
      const { step } = action;
      if (state.stepStatus[step] === "locked") return state;
      return { ...state, step };
    }

    case WizardActions.RESET_WIZARD:
      return createInitialWizardState();

    default:
      return state;
  }
}
