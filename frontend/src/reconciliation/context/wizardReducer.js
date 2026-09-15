import { WIZARD_STEPS, getVisibleSteps } from "../steps/stepConfig";

export const STEP_KEYS = WIZARD_STEPS.map((step) => step.key);

export const WizardActions = {
  SET_CONNECTOR: "SET_CONNECTOR",
  SET_ROLE_STATUS: "SET_ROLE_STATUS",
  SET_DATASET: "SET_DATASET",
  RESET_ROLE: "RESET_ROLE",
  SET_COMPARISON_TYPE: "SET_COMPARISON_TYPE",
  SET_INTERFACE_INDEX: "SET_INTERFACE_INDEX",
  CLEAR_INTERFACE_INDEX: "CLEAR_INTERFACE_INDEX",
  SET_ENTITY_JOIN_TEXT: "SET_ENTITY_JOIN_TEXT",
  SET_ENTITY_JOIN_PARSED: "SET_ENTITY_JOIN_PARSED",
  SET_ENTITY_JOIN_AREA: "SET_ENTITY_JOIN_AREA",
  CLEAR_ENTITY_JOIN: "CLEAR_ENTITY_JOIN",
  CLEAR_FIELD_CHANGE_NOTICE: "CLEAR_FIELD_CHANGE_NOTICE",
  SET_MAPPING_MODE: "SET_MAPPING_MODE",
  SET_MAPPING_SHEET: "SET_MAPPING_SHEET",
  SET_PARSED_MAPPING_SHEET: "SET_PARSED_MAPPING_SHEET",
  SET_BUSINESS_RULES: "SET_BUSINESS_RULES",
  SET_TRANSFORMATIONS: "SET_TRANSFORMATIONS",
  SET_MAPPING_RESOLUTION: "SET_MAPPING_RESOLUTION",
  SET_AGGREGATION_RULES: "SET_AGGREGATION_RULES",
  SET_TRANSFORMATION_MAPPING: "SET_TRANSFORMATION_MAPPING",
  SET_DRAFT_CONTRACT: "SET_DRAFT_CONTRACT",
  SET_CONTRACT_VALIDATION: "SET_CONTRACT_VALIDATION",
  SET_APPROVED_CONTRACT: "SET_APPROVED_CONTRACT",
  SET_DETERMINISTIC_CONTRACT: "SET_DETERMINISTIC_CONTRACT",
  SET_SHADOW_SNAPSHOTS: "SET_SHADOW_SNAPSHOTS",
  SET_ANCHOR_DATE: "SET_ANCHOR_DATE",
  SET_SHADOW_PREVIEW: "SET_SHADOW_PREVIEW",
  SET_SHADOW_APPROVAL: "SET_SHADOW_APPROVAL",
  SET_SCRIPT_TRANSFORMATIONS_MODE: "SET_SCRIPT_TRANSFORMATIONS_MODE",
  SET_GENERATED_SCRIPT: "SET_GENERATED_SCRIPT",
  SET_SCRIPT_PREVIEW: "SET_SCRIPT_PREVIEW",
  SET_SCRIPT_APPROVAL: "SET_SCRIPT_APPROVAL",
  SET_RECONCILIATION_RESULT: "SET_RECONCILIATION_RESULT",
  SET_AUTO_RUN: "SET_AUTO_RUN",
  RESTART_AUTO_RUN: "RESTART_AUTO_RUN",
  SET_APPROVAL_MODE: "SET_APPROVAL_MODE",
  CLAIM_FOR_HUMAN: "CLAIM_FOR_HUMAN",
  GO_TO_STEP: "GO_TO_STEP",
  COMPLETE_STEP: "COMPLETE_STEP",
  RESET_WIZARD: "RESET_WIZARD",
};

// Auto-run's resting state. Any change to one of the three input slots resets
// to this, which is what re-arms the auto-run for the new inputs.
function createIdleAutoRun() {
  return {
    status: "idle", // idle | running | blocked | done | error
    stage: null, // mapping | resolve | snapshots | validate | gate | approve | run
    // What started the pass in flight: "auto" for the unattended run that fires
    // on its own once all three inputs are present, "rerun" only after the user
    // clicked "Re-run source transformation". Progress labels read this so the
    // first pass says "Running" and never "Re-running".
    trigger: "auto",
    // Named gate checks that refused auto-approval (see lib/autoRun.js).
    failures: [],
    error: null,
    // The input signature this outcome belongs to — a completed/blocked run
    // stays settled until the inputs themselves change.
    signature: null,
  };
}

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
    // Which mapping flow the user chose on the Mapping step: "manual" |
    // "deterministic" | null (not yet chosen). Each flow keeps its own
    // derived state, so switching between them never discards the other
    // flow's progress.
    mappingMode: null,
    // Non-fatal notice shown when a field-selection / dataset change reset
    // derived work (an approved contract/preview) or orphaned a typed rule.
    // Surfaced plainly rather than silently swallowed — see
    // computeFieldChangeNotice. Cleared on a fresh connector/role reset.
    fieldChangeNotice: null,
    mappingSheet: null, // { name, size, file } — optional uploaded mapping sheet
    parsedMappingSheet: null, // /api/recon/mapping-sheet/parse response (structured rows)
    // Structured Business Rules Builder output — replaces the old free-text
    // `rulesText`. Each entry is { field, instruction }.
    transformationRules: [],
    matchingRules: [],
    filterRules: [],
    // Transformations Editor state: an ordered list of steps, each = one
    // ContractOperation ({ id, op, kind, field, params, enabled }). Authored
    // intent (like business rules), so it SURVIVES a dataset change —
    // invalidateDerivedState only resets the derived contract/preview, not this.
    transformations: [],
    // Did a HUMAN author/edit the steps above, or were they seeded from the
    // compiled chain? It decides what a replaced input slot does to them:
    // auto-seeded steps describe the OLD data and are discarded so the new data
    // recompiles (a stale chain is never partially reused), while steps a
    // person wrote are kept — losing those to a re-upload would destroy real
    // work. Set true by any edit in the Transformations drawer.
    transformationsAuthored: false,
    // Sequential AI mapping-resolution result from
    // /api/recon/mapping-resolution/resolve (auto-run once a mapping sheet
    // and both datasets are present): { relevant_fields, enriched_fields,
    // transformation_chain, operations, degraded, degraded_reason, provider }.
    // `operations` seeds `transformations` above (still hand-editable there);
    // this is kept separately so the Mapping Card can show the final resolved
    // operations without the raw mapping-sheet/reasoning intermediates. Null
    // until resolution has run.
    mappingResolution: null,
    // Structured aggregation rules ({ field, aggregation }) applied before
    // reconciliation.
    aggregationRules: [],
    mapping: null, // { display: [...], mapping: {...} } from /api/recon/mapping/infer (LLM), possibly hand-edited
    draftContract: null, // DraftContract JSON from /api/recon/contracts/compile
    validation: null, // { ok, gate1, gate2 } from /api/recon/contracts/validate
    contract: null, // approved TransformationContract (Manual flow) from /api/recon/contracts/approve
    // How `contract` came to be approved: "auto" (the auto-run gate cleared
    // every condition) or "manual" (a person clicked Approve). Null when
    // nothing is approved. Display/audit only — it never gates anything.
    approvalMode: null,
    // Set once a human edits the chain from Results. It survives a re-approval
    // (that is the point: a human touched this chain, so it stays human-owned)
    // and suppresses auto-approval for the rest of the run — re-approval from
    // here is always an explicit click, even if the edited chain would pass
    // every auto-approve condition. Cleared only by replacing an input slot,
    // which invalidates the whole run anyway.
    humanOwned: false,
    // Deterministic flow's auto-assembled, zero-operation contract (business
    // key + compare fields), approved at Run time. Kept separate from
    // `contract` so the two flows never overwrite each other's approved
    // contract.
    deterministicContract: null,
    // Review-Changes checkpoint (contract engine). Snapshots are created once
    // here and reused by the run so the reviewed shadow == the reconciled one.
    sourceSnapshotId: null,
    targetSnapshotId: null,
    // Optional explicit override ("YYYY-MM-DD" | null) for the run-time
    // anchor `date_window_filter`/`relative_date_reassign` evaluate against.
    // Left null so the backend resolves it itself — inferring it from the
    // target snapshot's own data when the contract has a relative-date rule
    // (see engine.anchor_inference), else wall-clock "now" — never guessed or
    // hardcoded here. Set this only to override that default (e.g. replaying
    // against a historical target extract the auto-inference couldn't read
    // confidently). Authored intent, like `transformations`/business rules — survives
    // a dataset change; only clearing shadowPreview/shadowApproved below.
    anchorDate: null,
    shadowPreview: null, // /api/recon/shadow-preview response (original/shadow/diffs/target/anchor_*)
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
    // The uploaded mapping workbook's INTERFACE INDEX (/mapping-sheet/interfaces):
    // { filename, sheets, index_sheet, interfaces: [{id, record, sheet, status,
    // match, candidates}], indexed, warnings, file }. A workbook is a collection
    // of interfaces, one worksheet each — this list IS the Dataset Type choice,
    // and the chosen interface's `sheet` is the only worksheet parsed. `file` is
    // retained so that scoped parse can be issued when the choice is made.
    // Null until a workbook is uploaded.
    interfaceIndex: null,
    // Free-text entity/join fallback, authored per side on Step 1 for when the
    // mapping sheet doesn't say which entities to fetch or how to join them.
    // `text` is what the user typed; `parsed` is the validated spec from
    // /api/recon/entity-join/parse. Kept per side and never merged, so one
    // side's entities can't leak into the other's. A present `parsed` OVERRIDES
    // the sheet-derived entities/join — typing it is a deliberate override.
    // `planningArea` is the manual SAP IBP planning-area choice, used when
    // neither the sheet nor the instruction names one. It matters because every
    // planning area exposes the same planning levels under the same field
    // names, so without it the right entity can't be told from the same entity
    // in another area — and the wizard must never pick one on the user's behalf.
    entityJoin: {
      source: { text: "", parsed: null, planningArea: "" },
      target: { text: "", parsed: null, planningArea: "" },
    },
    transformationSpec: createInitialTransformationSpec(),
    reconciliation: null,
    // Auto-run mode's progress/outcome for the current input triple. See
    // lib/autoRun.js — the wizard page drives it, every step reads it.
    autoRun: createIdleAutoRun(),
  };
}

// A field-selection / dataset change is only *sometimes* destructive. Typed
// business rules survive it (they are not cleared by invalidateDerivedState),
// but derived, field-dependent artifacts (an approved contract, an approved
// shadow/script preview) genuinely become stale. Rather than silently drop
// that work, we compute a human-readable notice describing exactly what got
// reset and which typed rules now reference fields that no longer exist.
function computeFieldChangeNotice(prevState, role, newDataset) {
  const spec = prevState.transformationSpec;
  const notices = [];

  if (spec.contract || spec.deterministicContract || spec.shadowApproved || spec.scriptApproval) {
    notices.push(
      `Your approved mapping/preview was reset because the ${role} dataset changed — re-review and re-approve on the Mapping step.`
    );
  }

  const otherRole = role === "source" ? "target" : "source";
  const columns = new Set([
    ...(newDataset?.columns ?? []),
    ...(prevState[otherRole]?.dataset?.columns ?? []),
  ]);
  const ruleFields = [];
  for (const key of ["transformationRules", "matchingRules", "filterRules", "aggregationRules"]) {
    for (const rule of spec[key] ?? []) {
      const field = rule?.field ?? rule?.source_field;
      if (field) ruleFields.push(field);
    }
  }
  const orphaned = [...new Set(ruleFields.filter((f) => !columns.has(f)))];
  if (orphaned.length > 0) {
    notices.push(
      `These rules now reference fields no longer in the data: ${orphaned.join(", ")}. Review them on the Mapping step.`
    );
  }

  return notices.length > 0 ? notices.join(" ") : null;
}

// The next step to unlock/navigate to, skipping steps hidden for the current
// engine (e.g. Review Changes in the script flow). Falls back to the canonical
// order when the engine mode isn't known yet.
function nextStepKey(state, key) {
  const steps = getVisibleSteps(state?.transformationSpec?.useScriptTransformations);
  const index = steps.findIndex((step) => step.key === key);
  return index >= 0 ? steps[index + 1]?.key ?? null : null;
}

// Steps that were seeded from the compiled chain describe the data that was
// loaded when they were compiled. Once a slot is replaced they are stale, so
// they are dropped and the chain is rebuilt from scratch against the new data.
// Hand-authored steps are kept — see `transformationsAuthored`.
function surviveReplacement(spec) {
  return spec.transformationsAuthored ? spec.transformations : [];
}

// Whenever a dataset (or connector) changes, any mapping/results derived from
// the *previous* data are stale — a mapping can reference columns that no
// longer exist in the newly loaded file (this is what produced errors like
// "Mapped source key column missing: 'Plant'"). Clear that derived state and
// re-lock the downstream steps so the mapping is recomputed against the fresh
// columns and the comparison is re-run.
function invalidateDerivedState(state, fieldChangeNotice = null) {
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
  // The run depends on the (now stale) contract and snapshots — re-lock it so
  // the user re-prepares the mapping against fresh data.
  stepStatus.reconciliation = "locked";

  return {
    ...state,
    stepStatus,
    // Replacing an input slot invalidates the previously compiled chain, its
    // header bindings, and any approval state (auto or manual) for this run
    // ENTIRELY — a stale chain is never partially reused against new data.
    // Resetting autoRun here is also what re-arms auto mode: once the replaced
    // slot is populated and all three are present again, the wizard page sees
    // an idle auto-run for a new input signature and restarts the full happy
    // path with no user click.
    autoRun: createIdleAutoRun(),
    // A contract compiled against the previous schemas is stale too — Gate 1
    // validates field references against the actual dataset columns, so a
    // dataset change invalidates the whole compile→validate→approve chain.
    transformationSpec: {
      ...state.transformationSpec,
      approvalMode: null,
      // A replacement ends the run that the human took ownership of, so the
      // new inputs start eligible for auto-approval again.
      humanOwned: false,
      // mappingMode is a UI choice, not derived data — preserved across a
      // dataset change so the user isn't bounced back to the method chooser.
      // fieldChangeNotice carries the human-readable explanation of what this
      // change reset (null clears any prior notice on a fresh connector/reset).
      fieldChangeNotice,
      mapping: null,
      // Re-run against the fresh columns — same reasoning as `mapping` above.
      // Auto-seeded steps go with it (they describe the replaced data); steps a
      // person wrote survive. Whichever remains, the resolution/auto-run
      // re-seeds only when the list ends up empty.
      transformations: surviveReplacement(state.transformationSpec),
      mappingResolution: null,
      draftContract: null,
      validation: null,
      contract: null,
      deterministicContract: null,
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
      // When this genuinely resets approved work or orphans a typed rule, a
      // notice is computed and surfaced rather than silently swallowed (1c).
      const notice = computeFieldChangeNotice(state, role, dataset);
      return invalidateDerivedState(
        {
          ...state,
          [role]: { ...state[role], dataset, status: "ready", error: null },
        },
        notice
      );
    }

    case WizardActions.RESET_ROLE: {
      const { role } = action;
      return invalidateDerivedState({ ...state, [role]: createInitialRoleState() });
    }

    case WizardActions.SET_COMPARISON_TYPE:
      return { ...state, comparisonType: action.comparisonType };

    case WizardActions.SET_INTERFACE_INDEX:
      // A newly uploaded workbook replaces the previous interface list. The
      // dataset-type choice and the identification derived from the OLD list
      // are cleared by the caller, not here — the two are separate dispatches
      // so replacing a workbook and picking an interface stay independent.
      return { ...state, interfaceIndex: action.interfaceIndex };

    case WizardActions.CLEAR_INTERFACE_INDEX:
      return { ...state, interfaceIndex: null };

    case WizardActions.SET_ENTITY_JOIN_TEXT: {
      const { role, text } = action;
      // Editing the text invalidates the spec parsed from the previous text —
      // the canvas must never be pre-populated from a stale instruction. The
      // planning area is a separate, deliberate choice and survives.
      return {
        ...state,
        entityJoin: {
          ...state.entityJoin,
          [role]: { ...state.entityJoin?.[role], text, parsed: null },
        },
      };
    }

    case WizardActions.SET_ENTITY_JOIN_AREA: {
      const { role, planningArea } = action;
      // Changing the area changes which entity the instruction resolves to, so
      // the previously parsed spec is stale — it must be re-resolved.
      return {
        ...state,
        entityJoin: {
          ...state.entityJoin,
          [role]: { text: "", ...state.entityJoin?.[role], planningArea, parsed: null },
        },
      };
    }

    case WizardActions.SET_ENTITY_JOIN_PARSED: {
      const { role, parsed } = action;
      return {
        ...state,
        entityJoin: {
          ...state.entityJoin,
          [role]: { text: "", ...state.entityJoin?.[role], parsed },
        },
      };
    }

    case WizardActions.CLEAR_ENTITY_JOIN: {
      const { role } = action;
      // Clearing hands the side back to whatever the sheet derived (if any).
      return {
        ...state,
        entityJoin: {
          ...state.entityJoin,
          [role]: { text: "", parsed: null, planningArea: "" },
        },
      };
    }

    case WizardActions.CLEAR_FIELD_CHANGE_NOTICE:
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, fieldChangeNotice: null },
      };

    case WizardActions.SET_MAPPING_MODE:
      // Purely records which flow the user is working in. Never clears the
      // other flow's derived state, so switching back and forth is lossless.
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, mappingMode: action.mappingMode },
      };

    case WizardActions.SET_MAPPING_SHEET:
      // A new (or removed) mapping sheet invalidates anything derived from the
      // previous one: parsed rows and the compiled/validated/approved contract
      // (or, in the script flow, the generated script/preview/approval).
      return {
        ...state,
        // Same rule as a dataset replacement: the chain, bindings and approval
        // derived from the previous sheet are discarded whole, and auto mode is
        // re-armed for the new sheet.
        autoRun: createIdleAutoRun(),
        transformationSpec: {
          ...state.transformationSpec,
          approvalMode: null,
          humanOwned: false,
          mappingSheet: action.mappingSheet,
          parsedMappingSheet: null,
          // Same rule as every other replacement — see surviveReplacement.
          transformations: surviveReplacement(state.transformationSpec),
          // A changed/removed mapping sheet invalidates the AI-resolved
          // transformation summary too — re-populated once the new sheet is
          // parsed and re-resolved. `transformations` itself is left alone
          // (see SET_TRANSFORMATIONS).
          mappingResolution: null,
          draftContract: null,
          validation: null,
          contract: null,
          generatedScript: null,
          scriptPreview: null,
          scriptApproval: null,
        },
      };

    case WizardActions.SET_PARSED_MAPPING_SHEET:
      // A re-parse (e.g. switching between interfaces of the SAME uploaded
      // workbook — SET_MAPPING_SHEET isn't re-dispatched for that, only this
      // action is) invalidates any AI mapping resolution derived from the
      // PREVIOUS sheet, same reasoning as SET_MAPPING_SHEET's own reset
      // below. `transformations` itself is left alone (still "authored intent"
      // once non-empty) — the resolution effect only re-seeds it when empty.
      return {
        ...state,
        // Switching interfaces swaps the mapping sheet's content, so the same
        // whole-run invalidation applies — and re-arms auto mode for it.
        autoRun: createIdleAutoRun(),
        transformationSpec: {
          ...state.transformationSpec,
          approvalMode: null,
          humanOwned: false,
          parsedMappingSheet: action.parsedMappingSheet,
          // A different interface is a different set of rules — auto-seeded
          // steps from the previous one are stale; hand-authored ones survive.
          transformations: surviveReplacement(state.transformationSpec),
          mappingResolution: null,
          draftContract: null,
          validation: null,
          contract: null,
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

    case WizardActions.SET_TRANSFORMATIONS:
      // `authored` says whether a human wrote these (drawer edit) or they were
      // seeded from the compiled chain. It only ever latches ON: once a person
      // has edited the chain, a later re-seed cannot quietly downgrade it back
      // to disposable. See surviveReplacement.
      return {
        ...state,
        transformationSpec: {
          ...state.transformationSpec,
          transformations: action.transformations,
          transformationsAuthored:
            state.transformationSpec.transformationsAuthored || Boolean(action.authored),
        },
      };

    case WizardActions.SET_MAPPING_RESOLUTION:
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, mappingResolution: action.mappingResolution },
      };

    case WizardActions.SET_AGGREGATION_RULES:
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, aggregationRules: action.rules },
      };

    case WizardActions.SET_TRANSFORMATION_MAPPING:
      // A changed field mapping invalidates the deterministic contract
      // assembled from the previous roles/targets — it must be rebuilt.
      return {
        ...state,
        transformationSpec: {
          ...state.transformationSpec,
          mapping: action.mapping,
          deterministicContract: null,
        },
      };

    case WizardActions.SET_DRAFT_CONTRACT:
      // A fresh draft supersedes any previous validation, approval, and the
      // shadow review derived from it.
      return {
        ...state,
        stepStatus: { ...state.stepStatus, reconciliation: "locked" },
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

    case WizardActions.SET_DETERMINISTIC_CONTRACT:
      // The Deterministic flow's auto-assembled contract. Stored separately
      // from the Manual `contract` and unlocks the run once it's approved.
      return {
        ...state,
        stepStatus: { ...state.stepStatus, reconciliation: "available" },
        transformationSpec: {
          ...state.transformationSpec,
          deterministicContract: action.contract,
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

    case WizardActions.SET_ANCHOR_DATE:
      // Changing the anchor changes what date_window_filter/
      // relative_date_reassign evaluate against, so any previously built
      // shadow/approval is stale — same reasoning SET_MAPPING_SHEET already
      // applies to a changed input.
      return {
        ...state,
        stepStatus: { ...state.stepStatus, reconciliation: "locked" },
        transformationSpec: {
          ...state.transformationSpec,
          anchorDate: action.anchorDate,
          shadowPreview: null,
          shadowApproved: null,
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

    case WizardActions.SET_AUTO_RUN:
      // Partial update — callers set only the fields they know (e.g. a stage
      // tick sets `stage` alone) without clearing the rest.
      return { ...state, autoRun: { ...state.autoRun, ...action.autoRun } };

    case WizardActions.RESTART_AUTO_RUN:
      // "Re-run source transformation" on the Mapping step. Re-arms the
      // unattended path so it replays all seven stages from the first one
      // (infer field mapping -> resolve the mapping sheet into a chain ->
      // snapshot -> validate -> gate -> approve -> reconcile) against the
      // inputs already loaded, instead of re-running the previously approved
      // contract as-is.
      //
      // Everything derived from the previous pass is dropped — a stale chain is
      // never partially reused, the same rule invalidateDerivedState applies to
      // a replaced input — with two deliberate exceptions:
      //   • the field mapping is KEPT, so stage 1 can merge the fresh inference
      //     over the rows a person edited (see runAutoPipeline). A re-run must
      //     never silently discard hand-confirmed Key/Compare assignments.
      //   • hand-authored transformation steps survive, as they do everywhere
      //     else; auto-seeded ones go, so the sheet recompiles them.
      // `humanOwned` clears because this click IS a human asking for the
      // automatic path again — but the Key/Compare gate still runs, so an
      // unconfirmed AI proposal blocks the run exactly as it always does.
      //
      // The auto-run slot is armed as "running" against a null signature rather
      // than reset to idle: the null signature is what makes useAutoRun fire
      // again for unchanged inputs, and marking it running in the same commit
      // keeps the Mapping step's own inference/resolution effects standing down
      // in the gap between this click and the hook's first dispatch — otherwise
      // a remounted step would re-resolve the mapping sheet in parallel with the
      // pipeline doing the same call.
      return {
        ...state,
        stepStatus: { ...state.stepStatus, reconciliation: "locked" },
        autoRun: { ...createIdleAutoRun(), status: "running", stage: "mapping", trigger: "rerun" },
        reconciliation: null,
        transformationSpec: {
          ...state.transformationSpec,
          approvalMode: null,
          humanOwned: false,
          transformations: surviveReplacement(state.transformationSpec),
          mappingResolution: null,
          draftContract: null,
          validation: null,
          contract: null,
          deterministicContract: null,
          sourceSnapshotId: null,
          targetSnapshotId: null,
          shadowPreview: null,
          shadowApproved: null,
        },
      };

    case WizardActions.SET_APPROVAL_MODE:
      return {
        ...state,
        transformationSpec: { ...state.transformationSpec, approvalMode: action.approvalMode },
      };

    case WizardActions.CLAIM_FOR_HUMAN:
      // "Edit transformation rules" from Results. The prior approval is
      // invalidated (the contract it approved no longer describes what will
      // run) but the user's steps are KEPT as the working draft — only the
      // approval is dropped, never the authored chain. `humanOwned` then holds
      // for the rest of the run, so re-approval is an explicit click even if
      // the edited chain would satisfy every auto-approve condition.
      return {
        ...state,
        stepStatus: { ...state.stepStatus, reconciliation: "locked" },
        autoRun: { ...createIdleAutoRun(), status: "done", signature: state.autoRun.signature },
        transformationSpec: {
          ...state.transformationSpec,
          humanOwned: true,
          approvalMode: null,
          contract: null,
          validation: null,
          shadowPreview: null,
          shadowApproved: null,
        },
      };

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
