import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../services/api";
import JsonViewer from "../../components/JsonViewer";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import {
  appendDatasetSide,
  buildMappingSheetPayload,
  buildRuleFieldOptions,
  buildValueMappingFormData,
  cleanAggregationRules,
  cleanBusinessRules,
  hasMappingPayload,
  mergeGeneratedMapping,
  missingValueMappingRequirements,
  rebuildMapping,
  sampleRows,
} from "../lib/payload";
import {
  createBothSnapshots,
  generateInsightsForRun,
  identicalDatasetReason,
  runContractReconciliation,
} from "../lib/reconRun";
import StepShell from "../components/StepShell";
import MappingCard from "../components/MappingCard";
import MappingEditor from "../components/MappingEditor";
import BusinessRulesBuilder from "../components/BusinessRulesBuilder";
import AggregationRulesBuilder from "../components/AggregationRulesBuilder";
import StatusBadge from "../components/StatusBadge";
import TransformationPreviewPanel from "../components/TransformationPreviewPanel";
import ShadowPreviewPanel from "../components/ShadowPreviewPanel";
import { Button, Badge } from "@bristlecone/canopy";

const DOC_ACCEPT = ".xlsx,.xls,.csv";

// Applied vs excluded distinct-value counts for one field's value mapping.
// Applied = VERY_HIGH/HIGH (what the executor writes to the shadow); excluded
// = MEDIUM/NONE/OUT_OF_SCOPE (held out, never reconciled). Powers the
// Deterministic path's Run Reconciliation confirmation dialog.
function appliedExcludedCounts(valueMapping) {
  const matches = valueMapping?.matches ?? [];
  let applied = 0;
  let excluded = 0;
  for (const m of matches) {
    if (m.confidence === "very_high" || m.confidence === "high") applied += 1;
    else excluded += 1;
  }
  return { applied, excluded };
}

function TransformationSpecStep() {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();
  const { source, target, comparisonType, transformationSpec } = state;
  const {
    mappingMode,
    mappingSheet,
    parsedMappingSheet,
    transformationRules,
    matchingRules,
    filterRules,
    aggregationRules,
    mapping,
    valueMappings,
    draftContract,
    validation,
    contract,
    useScriptTransformations,
  } = transformationSpec;

  const setMappingMode = (mode) =>
    dispatch({ type: WizardActions.SET_MAPPING_MODE, mappingMode: mode });

  const fieldOptions = useMemo(
    () => buildRuleFieldOptions(source, target, parsedMappingSheet),
    [source, target, parsedMappingSheet],
  );
  const setRuleCategory = (category, rules) =>
    dispatch({ type: WizardActions.SET_BUSINESS_RULES, category, rules });

  // Aggregation rules operate on SOURCE fields (measures + date fields), so the
  // dropdown lists source columns only.
  const sourceColumns = useMemo(() => source.dataset?.columns ?? [], [source.dataset]);
  const sourceFieldOptions = useMemo(
    () => sourceColumns.map((c) => ({ value: c, label: c })),
    [sourceColumns],
  );
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState(null);
  // Non-blocking notice from the inference call: a provider-failover message
  // (served by OpenAI) or a degraded reason (no mapping could be generated).
  const [mapNotice, setMapNotice] = useState(null);
  const [valueMappingLoading, setValueMappingLoading] = useState(false);
  const [valueMappingError, setValueMappingError] = useState(null);
  const [valueMappingSuccess, setValueMappingSuccess] = useState(false);
  const [parseLoading, setParseLoading] = useState(false);
  const [parseError, setParseError] = useState(null);
  const [compileLoading, setCompileLoading] = useState(false);
  const [contractError, setContractError] = useState(null);
  // Non-blocking notice when an LLM provider failover occurred (Groq→OpenAI) or
  // when every AI provider was unavailable (spec points 5 & 6).
  const [providerNotice, setProviderNotice] = useState(null);
  const [approveLoading, setApproveLoading] = useState(false);
  // Deterministic-path Run Reconciliation (compile → approve → run, no shadow
  // preview). Its own loading/error so it never collides with the Manual-path
  // contract compile/approve state above.
  const [detRunning, setDetRunning] = useState(false);
  const [detRunError, setDetRunError] = useState(null);
  // Contract JSON is hidden by default (progressive disclosure for business users).
  const [showContract, setShowContract] = useState(false);
  const mappingSheetInputRef = useRef(null);
  // Signature of the (source, target) datasets we last auto-mapped. When the
  // user re-uploads or re-fetches, the dataset id changes and the reducer
  // clears the stale mapping, so a new signature re-triggers auto-mapping
  // against the fresh columns — no restart needed.
  const mappedSignatureRef = useRef(null);

  const datasetSignature = (src, tgt) =>
    `${src?.dataset?.datasetId ?? src?.dataset?.fetchedAt ?? ""}::` +
    `${tgt?.dataset?.datasetId ?? tgt?.dataset?.fetchedAt ?? ""}`;

  // Feature flag (USE_SCRIPT_TRANSFORMATIONS): fetched once to decide whether
  // Section D is the contract-based flow or the Transformation Preview +
  // Approval flow. Defaults to the contract flow if the check fails.
  useEffect(() => {
    if (useScriptTransformations !== null) return;
    let cancelled = false;
    api
      .get("/api/recon/transformations/mode")
      .then((res) => {
        if (!cancelled) {
          dispatch({
            type: WizardActions.SET_SCRIPT_TRANSFORMATIONS_MODE,
            useScriptTransformations: Boolean(res.data?.use_script_transformations),
          });
        }
      })
      .catch(() => {
        if (!cancelled) {
          dispatch({ type: WizardActions.SET_SCRIPT_TRANSFORMATIONS_MODE, useScriptTransformations: false });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [useScriptTransformations, dispatch]);

  // ── mapping sheet upload + parse ──────────────────────────────────────────
  const handleMappingSheetFile = async (file) => {
    dispatch({
      type: WizardActions.SET_MAPPING_SHEET,
      mappingSheet: file ? { name: file.name, size: file.size, file } : null,
    });
    setParseError(null);
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);
    setParseLoading(true);
    try {
      const res = await api.post("/api/recon/mapping-sheet/parse", formData);
      dispatch({ type: WizardActions.SET_PARSED_MAPPING_SHEET, parsedMappingSheet: res.data });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setParseError(typeof detail === "string" ? detail : "Could not parse the mapping sheet.");
    } finally {
      setParseLoading(false);
    }
  };

  // Remove the uploaded mapping sheet: SET_MAPPING_SHEET(null) also clears the
  // parsed rows and the compiled/validated/approved contract (reducer), so
  // contract eligibility falls back to the field mapping with no page refresh.
  const removeMappingSheet = () => {
    dispatch({ type: WizardActions.SET_MAPPING_SHEET, mappingSheet: null });
    setParseError(null);
    if (mappingSheetInputRef.current) mappingSheetInputRef.current.value = "";
  };

  // ── LLM-inferred field mapping (no-mapping-sheet path) ────────────────────
  // Infers the source→target FIELD mapping (column→column + Key/Compare role)
  // from a sample of the fetched data, via the Groq→OpenAI failover client.
  // FIELD mapping only — value-to-value mapping stays the deterministic
  // matcher's job. `preserveEdits` keeps rows the user hand-edited and refreshes
  // only the untouched generated ones (Regenerate); the first run replaces.
  const runInference = useCallback(async ({ preserveEdits = false, forceLlm = false } = {}) => {
    if (!source.dataset || !target.dataset) return;

    const formData = new FormData();
    // Auto-selected MDT/recommended fields (tracked per dataset by the
    // connector workspaces) are excluded here — before the inference ever sees
    // them — so they are never proposed as field-mapping candidates. They feed
    // the deterministic matcher as evidence and stay in the dataset itself for
    // tracking/validation/approval; only the inference request omits them.
    const okSource = appendDatasetSide(formData, "source", source, source.dataset?.mdtFields);
    const okTarget = appendDatasetSide(formData, "target", target, target.dataset?.mdtFields);
    if (!okSource || !okTarget) {
      setMapError("Source or target data is no longer available. Go back and re-fetch or re-upload it.");
      return;
    }

    // Attribute-library (tier 1) lookup key: connectors + comparison type + the
    // FULL per-side column sets. These same source.dataset.columns are sent to
    // /contracts/compile as source_schema/target_schema, so the canonical key
    // computed here matches the one store-back uses on run completion — that
    // equality is what makes an identical column set reuse the stored mapping.
    // `forceLlm` (Regenerate) skips the library and re-infers via the LLM.
    formData.append("source_connector", source.kind ?? "excel");
    formData.append("target_connector", target.kind ?? "excel");
    formData.append("comparison_type", comparisonType?.id ?? "custom");
    formData.append("source_columns", JSON.stringify(source.dataset?.columns ?? []));
    formData.append("target_columns", JSON.stringify(target.dataset?.columns ?? []));
    if (forceLlm) formData.append("regenerate", "true");

    setMapLoading(true);
    setMapError(null);
    setMapNotice(null);
    try {
      const res = await api.post("/api/recon/mapping/infer", formData);
      const data = res.data ?? {};
      const inferred = data.display ?? [];
      const nextDisplay = preserveEdits
        ? mergeGeneratedMapping(mapping?.display, inferred)
        : inferred;
      dispatch({
        type: WizardActions.SET_TRANSFORMATION_MAPPING,
        mapping: {
          display: nextDisplay,
          mapping: rebuildMapping(nextDisplay, data.mapping?.options),
          // Provenance of the whole card so MappingEditor can label the source
          // ("Generated via Vector Library" vs "Generated via Groq/OpenAI").
          origin: {
            source: data.source ?? null,
            provider: data.provider ?? null,
            version: data.library_version ?? null,
            confidence: data.confidence ?? null,
          },
        },
      });
      // Surface a degraded reason (nothing generated) or a provider-failover
      // notice (served by OpenAI) without blocking — the table is still usable.
      if (data.degraded && data.degraded_reason) setMapNotice(data.degraded_reason);
      else if (data.provider_notice) setMapNotice(data.provider_notice);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setMapError(typeof detail === "string" ? detail : "Field-mapping inference failed.");
    } finally {
      setMapLoading(false);
    }
  }, [source, target, comparisonType, dispatch, mapping]);

  // Generate suggested mappings automatically when this step has both datasets
  // and no mapping yet — including after a re-upload/re-fetch, which changes
  // the dataset signature. Deferred with a timeout so the fetch (and its
  // setState) doesn't run synchronously inside the effect body.
  useEffect(() => {
    if (mapping) return;
    if (!source.dataset || !target.dataset) return;
    const signature = datasetSignature(source, target);
    if (mappedSignatureRef.current === signature) return;
    mappedSignatureRef.current = signature;
    const id = setTimeout(() => runInference({ preserveEdits: false }), 0);
    return () => clearTimeout(id);
  }, [mapping, source, target, runInference]);

  // ── deterministic value mapping (Material->PRDID, ProductionPlant->LOCID) ──
  const missingValueMappingReqs = useMemo(
    () => missingValueMappingRequirements(mapping?.display),
    [mapping],
  );
  const canRunValueMapping =
    Boolean(source.dataset && target.dataset) && missingValueMappingReqs.length === 0;

  const runValueMapping = async () => {
    const formData = buildValueMappingFormData(source, target);
    if (!formData) {
      setValueMappingError(
        "Source or target data is no longer available. Go back and re-fetch or re-upload it.",
      );
      return;
    }
    setValueMappingLoading(true);
    setValueMappingError(null);
    setValueMappingSuccess(false);
    try {
      const res = await api.post("/api/recon/value-mapping/run", formData);
      dispatch({
        type: WizardActions.SET_VALUE_MAPPINGS,
        valueMappings: {
          product: res.data?.product ?? null,
          location: res.data?.location ?? null,
          // Recommended-for-Deterministic-Mapping auxiliary evidence fields
          // (tier + fill rate + consumed). Surfaced on the Mapping Review page;
          // never sent into the compile payload (see value_mappings below).
          auxiliaryFields: res.data?.auxiliary_fields ?? null,
        },
      });
      setValueMappingSuccess(true);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setValueMappingError(typeof detail === "string" ? detail : "Deterministic mapping failed.");
    } finally {
      setValueMappingLoading(false);
    }
  };

  // ── deterministic reconciliation (Flow 1) ─────────────────────────────────
  // Auto-assembles a zero-operation contract from the confirmed field mapping
  // (business_key/compare_fields) + the value mappings (the executor applies
  // only VERY_HIGH/HIGH and holds out the rest), approves it, and runs — with
  // NO shadow preview. The confirmation dialog is this flow's only human gate.
  const canRunDeterministicRecon = Boolean(valueMappings) && missingValueMappingReqs.length === 0;

  const runDeterministicReconciliation = async () => {
    if (!canRunDeterministicRecon) return;

    const p = appliedExcludedCounts(valueMappings?.product);
    const l = appliedExcludedCounts(valueMappings?.location);
    const proceed = window.confirm(
      `${p.applied} materials + ${l.applied} plants will be applied to the shadow source.\n` +
        `${p.excluded} materials + ${l.excluded} plants are excluded ` +
        `(MEDIUM / NONE / out-of-scope) and will not be reconciled.\n\n` +
        `Proceed with reconciliation?`,
    );
    if (!proceed) return;

    setDetRunning(true);
    setDetRunError(null);
    try {
      const identical = identicalDatasetReason(source, target);
      if (identical) {
        throw new Error(
          `Source and target must be different datasets — ${identical}. ` +
            "Re-upload the correct file for one side before reconciling.",
        );
      }

      // Same compile payload as the Manual flow, but with no rules/aggregation
      // (zero Groq operations) and the value mappings always attached — the
      // confirmation dialog above is the approval.
      const payload = {
        mapping_sheet: buildMappingSheetPayload(null, mapping),
        rules: "",
        transformation_rules: [],
        matching_rules: [],
        filter_rules: [],
        aggregation_rules: [],
        business_key: (mapping?.mapping?.key_fields ?? []).map((f) => ({
          source_field: f.source_col,
          target_field: f.target_col,
        })),
        compare_fields: (mapping?.mapping?.compare_fields ?? []).map((f) => ({
          source_field: f.source_col,
          target_field: f.target_col,
        })),
        value_mappings: [valueMappings?.product, valueMappings?.location].filter(Boolean),
        source_schema: source.dataset?.columns ?? [],
        target_schema: target.dataset?.columns ?? [],
        comparison_type: comparisonType?.id ?? "custom",
        source_type: source.kind ?? "excel",
        target_type: target.kind ?? "excel",
        actor: "wizard-user",
      };

      const compileRes = await api.post("/api/recon/contracts/compile", payload);
      const draft = compileRes.data?.draft;
      const approveRes = await api.post("/api/recon/contracts/approve", {
        draft,
        approved_by: "wizard-user",
      });
      const detContract = approveRes.data?.contract;
      dispatch({ type: WizardActions.SET_DETERMINISTIC_CONTRACT, contract: detContract });

      const { sourceSnapshot, targetSnapshot } = await createBothSnapshots(
        source,
        target,
        comparisonType,
      );
      // No expected_shadow_fingerprint — the Deterministic path has no
      // shadow-approval gate (resolved design).
      const result = await runContractReconciliation({
        contract: detContract,
        sourceSnapshotId: sourceSnapshot.snapshot_id,
        targetSnapshotId: targetSnapshot.snapshot_id,
      });
      dispatch({
        type: WizardActions.SET_RECONCILIATION_RESULT,
        result: {
          ...result,
          source_snapshot: result.source_snapshot ?? sourceSnapshot,
          target_snapshot: result.target_snapshot ?? targetSnapshot,
        },
      });
      dispatch({ type: WizardActions.COMPLETE_STEP, step: "transformationSpec" });
      dispatch({ type: WizardActions.COMPLETE_STEP, step: "reconciliation" });
      dispatch({ type: WizardActions.GO_TO_STEP, step: "reconciliation" });
      generateInsightsForRun(result.run_id);
      navigate("/reconciliation/reconciliation");
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setDetRunError(
        typeof detail === "string" ? detail : err?.message || "Reconciliation failed.",
      );
    } finally {
      setDetRunning(false);
    }
  };

  // ── contract lifecycle: compile → validate → approve ──────────────────────
  const validateDraft = useCallback(
    async (draft) => {
      const res = await api.post("/api/recon/contracts/validate", {
        draft,
        source_columns: source.dataset?.columns ?? [],
        target_columns: target.dataset?.columns ?? [],
        source_sample: sampleRows(source),
        target_sample: sampleRows(target),
        actor: "wizard-user",
      });
      dispatch({ type: WizardActions.SET_CONTRACT_VALIDATION, validation: res.data });
      return res.data;
    },
    [source, target, dispatch],
  );

  // Defensive pre-flight checks: /contracts/compile's `CompileRequest`
  // requires mapping_sheet + rules + source_schema + target_schema +
  // comparison_type + source_type + target_type, wrapped as one object (never
  // the raw parsed-sheet object posted directly as the request body — that
  // 422s with `loc: ["body", "source_schema"]` because it never arrives inside
  // a "mapping_sheet" field). Surface each missing piece with a specific,
  // actionable message instead of letting a vague 422 reach the user.
  const validateBeforeGeneratingContract = (mappingSheetPayload) => {
    const sourceColumns = source.dataset?.columns ?? [];
    const targetColumns = target.dataset?.columns ?? [];
    if (!sourceColumns.length || !targetColumns.length) {
      return "Source and target data must be loaded (with columns detected) before generating transformation rules. Go back to Steps 1–2.";
    }
    if (!comparisonType?.id) {
      return "Select a dataset type before generating transformation rules.";
    }
    if (mappingSheet?.name && !parsedMappingSheet) {
      return "The uploaded mapping sheet hasn't finished parsing yet (or failed to parse). Wait for parsing to complete, or remove it and confirm a field mapping instead.";
    }
    if (!hasMappingPayload(mappingSheetPayload)) {
      return "Upload a mapping sheet or confirm at least one field mapping first.";
    }
    return null;
  };

  const generateContract = async () => {
    const mappingSheetPayload = buildMappingSheetPayload(parsedMappingSheet, mapping);
    const validationError = validateBeforeGeneratingContract(mappingSheetPayload);
    if (validationError) {
      setContractError(validationError);
      return;
    }

    // /contracts/compile's CompileRequest requires mapping_sheet to be
    // WRAPPED alongside these sibling fields — never post the parsed-sheet
    // object by itself as the request body.
    const payload = {
      mapping_sheet: mappingSheetPayload,
      // Legacy free-text field, retired from this UI — the Business Rules
      // Builder below sends structured rules instead (still accepted by
      // the backend from any older caller that only has this field).
      rules: "",
      transformation_rules: cleanBusinessRules(transformationRules),
      matching_rules: cleanBusinessRules(matchingRules),
      filter_rules: cleanBusinessRules(filterRules),
      aggregation_rules: cleanAggregationRules(aggregationRules),
      // The Rules step's confirmed field mapping — human-owned, never
      // inferred by the compiler (see ContractBody's docstring).
      business_key: (mapping?.mapping?.key_fields ?? []).map((f) => ({
        source_field: f.source_col,
        target_field: f.target_col,
      })),
      compare_fields: (mapping?.mapping?.compare_fields ?? []).map((f) => ({
        source_field: f.source_col,
        target_field: f.target_col,
      })),
      // Manual flow never applies deterministic value mappings — those belong
      // to the Deterministic flow (runDeterministicReconciliation), which
      // attaches them on its own separate contract.
      value_mappings: [],
      source_schema: source.dataset?.columns ?? [],
      target_schema: target.dataset?.columns ?? [],
      comparison_type: comparisonType?.id ?? "custom",
      source_type: source.kind ?? "excel",
      target_type: target.kind ?? "excel",
      actor: "wizard-user",
    };
    // TEMP DIAGNOSTIC — confirms the exact shape leaving the browser. Remove
    // once the request/response shape is confirmed in the field.
    console.log("Compile payload", payload);

    setCompileLoading(true);
    setContractError(null);
    setProviderNotice(null);
    try {
      const res = await api.post("/api/recon/contracts/compile", payload);
      const draft = res.data?.draft;
      // Surface the AI-provider fallback / unavailability notice, if any. The
      // workflow always continues (OpenAI or the deterministic fallback).
      setProviderNotice(res.data?.provider_notice ?? null);
      dispatch({ type: WizardActions.SET_DRAFT_CONTRACT, draftContract: draft });
      await validateDraft(draft);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setContractError(typeof detail === "string" ? detail : "Transformation rules generation failed.");
    } finally {
      setCompileLoading(false);
    }
  };

  const approveContract = async () => {
    if (!draftContract) return;
    setApproveLoading(true);
    setContractError(null);
    try {
      const res = await api.post("/api/recon/contracts/approve", {
        draft: draftContract,
        approved_by: "wizard-user",
      });
      dispatch({ type: WizardActions.SET_APPROVED_CONTRACT, contract: res.data?.contract });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setContractError(typeof detail === "string" ? detail : "Transformation rules approval failed.");
    } finally {
      setApproveLoading(false);
    }
  };

  const hasMappingSheet = Boolean(mappingSheet?.name);
  const targetColumns = target.dataset?.columns ?? [];
  const gate1 = validation?.gate1;
  const gate2 = validation?.gate2;
  const canGenerate =
    Boolean(source.dataset && target.dataset) &&
    (Boolean(parsedMappingSheet?.rows?.length) || Boolean(mapping?.display?.length));

  // The run happens inline on this page for the Deterministic flow and for the
  // Manual contract flow (via ShadowPreviewPanel), so the generic Continue is
  // hidden there — advancement is via "Run Reconciliation". The Manual script
  // flow still advances to Results via Continue (its inline preview/approval is
  // TransformationPreviewPanel; the run happens on the Results step).
  const runsInline =
    mappingMode === "deterministic" || (mappingMode === "manual" && !useScriptTransformations);
  const hideContinue = mappingMode === null || runsInline;

  return (
    <StepShell stepKey="transformationSpec" canContinue hideContinue={hideContinue}>
      {/* Persistent at-a-glance mapping summary + back-links to Steps 2/3.
          Anchored at #mapping-card (linked from the sidebar). */}
      <MappingCard />

      {/* Mapping-method chooser (no method picked yet) */}
      {mappingMode === null && (
        <section className="wizard-section">
          <h3 className="wizard-section__title">Choose a mapping method</h3>
          <p className="wizard-field__help">
            Pick how the source is aligned to the target. You can switch methods later without losing
            either one's progress.
          </p>
          <div className="wizard-option-grid">
            <button
              type="button"
              className="wizard-option-card"
              onClick={() => setMappingMode("manual")}
            >
              <span className="wizard-option-card__label">Manual Mapping</span>
              <span className="wizard-option-card__meta">
                Mapping sheet · rules · transformations · reviewed shadow preview
              </span>
            </button>
            <button
              type="button"
              className="wizard-option-card"
              onClick={() => setMappingMode("deterministic")}
            >
              <span className="wizard-option-card__label">Deterministic Mapping</span>
              <span className="wizard-option-card__meta">
                Tiered value matching · VERY_HIGH/HIGH applied · no transformation rules
              </span>
            </button>
          </div>
        </section>
      )}

      {mappingMode !== null && (
        <button type="button" className="wizard-link" onClick={() => setMappingMode(null)}>
          ← Change mapping method
        </button>
      )}

      {/* ── Flow 1: Deterministic Mapping ──────────────────────────────────
          Field mapping + Run Deterministic Mapping + View Mapping Review +
          Run Reconciliation only. No mapping sheet, rules, transformations,
          aggregation, or transformation-rules approval block. */}
      {mappingMode === "deterministic" && (
        <>
          <section className="wizard-section">
            <h3 className="wizard-section__title">Field Mapping</h3>
            <p className="wizard-field__help">
              Confirm the source-to-target field mapping used for deterministic matching (Location →
              LOCID, Product → PRDID, Period → PERIODID0_TSTAMP as Key; Quantity → SALESORDERREQUEST
              as Compare).
            </p>
            <MappingEditor
              mapping={mapping}
              sourceColumns={sourceColumns}
              targetColumns={targetColumns}
              loading={mapLoading}
              error={mapError}
              notice={mapNotice}
              onChange={(next) =>
                dispatch({ type: WizardActions.SET_TRANSFORMATION_MAPPING, mapping: next })
              }
              onRegenerate={() => {
                mappedSignatureRef.current = datasetSignature(source, target);
                // Regenerate always drops to the LLM (tier 2) and relabels, even
                // if a library entry exists — the user asked for a fresh inference.
                runInference({ preserveEdits: true, forceLlm: true });
              }}
            />

            <div className="contract-actions" style={{ marginTop: 10 }}>
              <Button
                type="button"
                variant="outline"
                onClick={runValueMapping}
                disabled={!canRunValueMapping || valueMappingLoading}
                title={
                  missingValueMappingReqs.length
                    ? "Confirm these field mappings first: " +
                      missingValueMappingReqs
                        .map((r) => `${r.source} → ${r.target} (${r.role === "key" ? "Key" : "Compare"})`)
                        .join("; ")
                    : undefined
                }
              >
                {valueMappingLoading ? "Matching…" : "Run Deterministic Mapping"}
              </Button>
              {valueMappings && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => navigate("/reconciliation/transformation-spec/mapping-review")}
                >
                  View Mapping Review
                </Button>
              )}
            </div>
            {valueMappingError && <p className="wizard-step__error">⚠️ {valueMappingError}</p>}
            {valueMappingSuccess && !valueMappingError && (
              <p className="wizard-step__success">
                ✓ Deterministic mapping complete. Open "View Mapping Review" to inspect the tiers, or
                run reconciliation below.
              </p>
            )}
          </section>

          <section className="wizard-section">
            <h3 className="wizard-section__title">Reconciliation</h3>
            <p className="wizard-field__help">
              Applies the VERY_HIGH/HIGH value mappings and reconciles immediately.
              MEDIUM/NONE/out-of-scope values are excluded. There is no separate preview — Run
              Reconciliation shows the counts to confirm, then runs.
            </p>
            <div className="contract-actions">
              <Button
                type="button"
                variant="primary"
                size="lg"
                onClick={runDeterministicReconciliation}
                disabled={!canRunDeterministicRecon || detRunning}
                title={
                  !valueMappings
                    ? "Run Deterministic Mapping first."
                    : missingValueMappingReqs.length
                      ? "Confirm the required field mappings first."
                      : undefined
                }
              >
                {detRunning ? "Reconciling…" : "Run Reconciliation"}
              </Button>
            </div>
            {!valueMappings && (
              <p className="wizard-field__help">
                Run Deterministic Mapping first to enable reconciliation.
              </p>
            )}
            {detRunError && <p className="wizard-step__error">⚠️ {detRunError}</p>}
          </section>
        </>
      )}

      {/* ── Flow 2: Manual Mapping ─────────────────────────────────────────
          The existing Rules-page content, unchanged, plus the relocated inline
          Transformation Preview (shadow diff + Approve Shadow + inline Run) for
          the contract engine. */}
      {mappingMode === "manual" && (
        <>
          {/* Section A — Mapping Sheet */}
          <section className="wizard-section">
            <h3 className="wizard-section__title">Mapping Sheet</h3>
            <p className="wizard-field__help">Optional. .xlsx, .xls, or .csv.</p>

            {/* Hidden input; driven by the buttons below so Replace can re-open it. */}
            <input
              ref={mappingSheetInputRef}
              type="file"
              accept={DOC_ACCEPT}
              style={{ display: "none" }}
              onChange={(e) => handleMappingSheetFile(e.target.files?.[0] ?? null)}
            />

            <div className="doc-upload">
              {mappingSheet?.name ? (
                <div className="doc-upload__file">
                  <Badge variant="success">✓ {mappingSheet.name}</Badge>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => mappingSheetInputRef.current?.click()}
                  >
                    Replace
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={removeMappingSheet}
                  >
                    Remove
                  </Button>
                </div>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => mappingSheetInputRef.current?.click()}
                >
                  Upload Mapping Sheet
                </Button>
              )}
              {parseLoading && <span className="wizard-step__hint">Parsing…</span>}
              {parsedMappingSheet && (
                <Badge variant="success">✓ {parsedMappingSheet.row_count} rows</Badge>
              )}
              {parseError && <p className="wizard-step__error">⚠️ {parseError}</p>}
            </div>
          </section>

          {/* Section B — Rules */}
          <section className="wizard-section">
            <h3 className="wizard-section__title">Rules</h3>
            <p className="wizard-field__help">
              Configure transformations, matching, filters, and aggregation.
            </p>
            <BusinessRulesBuilder
              fieldOptions={fieldOptions}
              transformationRules={transformationRules}
              matchingRules={matchingRules}
              filterRules={filterRules}
              onChangeCategory={setRuleCategory}
            />
          </section>

          {/* Section B2 — Aggregation */}
          <section className="wizard-section">
            <h3 className="wizard-section__title">Aggregation</h3>
            <p className="wizard-field__help">Group and summarize source data.</p>
            <AggregationRulesBuilder
              fieldOptions={sourceFieldOptions}
              rules={aggregationRules ?? []}
              onChange={(rules) => dispatch({ type: WizardActions.SET_AGGREGATION_RULES, rules })}
            />
          </section>

          {/* Section C — Mapping */}
          <section className="wizard-section">
            <h3 className="wizard-section__title">Mapping</h3>
            <p className="wizard-field__help">Review source-to-target mappings.</p>
            <MappingEditor
              mapping={mapping}
              sourceColumns={sourceColumns}
              targetColumns={targetColumns}
              loading={mapLoading}
              error={mapError}
              notice={mapNotice}
              onChange={(next) =>
                dispatch({ type: WizardActions.SET_TRANSFORMATION_MAPPING, mapping: next })
              }
              onRegenerate={() => {
                mappedSignatureRef.current = datasetSignature(source, target);
                // Regenerate always drops to the LLM (tier 2) and relabels, even
                // if a library entry exists — the user asked for a fresh inference.
                runInference({ preserveEdits: true, forceLlm: true });
              }}
            />
          </section>

          {/* Section D — Transformation Preview (USE_SCRIPT_TRANSFORMATIONS) or the
              contract flow, decided by the backend feature flag. */}
          {useScriptTransformations && <TransformationPreviewPanel />}
          {!useScriptTransformations && (
            <section className="wizard-section">
              <h3 className="wizard-section__title">Transformation Rules</h3>
              <p className="wizard-field__help">Rules used to align source and target data.</p>

              <div className="contract-checklist">
                <StatusBadge
                  ok={hasMappingSheet ? Boolean(parsedMappingSheet) : null}
                  label={
                    hasMappingSheet
                      ? `Mapping Sheet ${parsedMappingSheet ? "Parsed" : "Uploaded"}`
                      : "Mapping Sheet (optional — field mapping used instead)"
                  }
                />
                <StatusBadge ok={draftContract ? true : null} label="Transformation Rules Generated" />
                <StatusBadge ok={gate1 ? gate1.ok : null} label="Structure Check" />
                <StatusBadge ok={gate2 ? gate2.ok : null} label="Sample Validation" />
                <StatusBadge
                  ok={contract ? true : null}
                  label={contract ? `Approved — Rules v${contract.contract_version}` : "Approved"}
                />
              </div>

              <div className="contract-actions">
                <Button
                  type="button"
                  variant="primary"
                  onClick={generateContract}
                  disabled={!canGenerate || compileLoading}
                >
                  {compileLoading
                    ? "Generating…"
                    : draftContract
                      ? "Regenerate Transformation Rules"
                      : "Generate Transformation Rules"}
                </Button>
                <Button
                  type="button"
                  variant="primary"
                  onClick={approveContract}
                  disabled={!draftContract || !validation?.ok || Boolean(contract) || approveLoading}
                >
                  {approveLoading
                    ? "Approving…"
                    : contract
                      ? "Transformation Rules Approved"
                      : "Approve Transformation Rules"}
                </Button>
              </div>

              {contractError && <p className="wizard-step__error">⚠️ {contractError}</p>}

              {providerNotice && <p className="wizard-step__hint">ℹ️ {providerNotice}</p>}

              {validation && !validation.ok && (
                <div className="contract-gate-errors">
                  {(gate1?.errors ?? []).map((msg, i) => (
                    <p key={`g1-${i}`} className="wizard-step__error">
                      Structure Check: {msg}
                    </p>
                  ))}
                  {(gate2?.errors ?? []).map((msg, i) => (
                    <p key={`g2-${i}`} className="wizard-step__error">
                      Sample Validation: {msg}
                    </p>
                  ))}
                </div>
              )}
              {(gate1?.info ?? []).length > 0 && (
                <div className="contract-gate-info">
                  {gate1.info.map((msg, i) => (
                    <p key={`g1i-${i}`} className="wizard-step__hint">
                      ✓ {msg}
                    </p>
                  ))}
                </div>
              )}
              {validation?.ok && (gate2?.warnings ?? []).length > 0 && (
                <div className="contract-gate-errors">
                  {gate2.warnings.map((msg, i) => (
                    <p key={`g2w-${i}`} className="wizard-step__hint">
                      Sample Validation warning: {msg}
                    </p>
                  ))}
                </div>
              )}

              {draftContract && (
                <>
                  <div className="contract-summary">
                    <Badge variant="default">
                      Business Keys: {draftContract.business_key?.length ?? 0}
                    </Badge>
                    <Badge variant="default">
                      Compare Fields: {draftContract.compare_fields?.length ?? 0}
                    </Badge>
                    <Badge variant="default">
                      Operations: {draftContract.operations?.length ?? 0}
                    </Badge>
                    <Badge variant="default">
                      Generation Method: {draftContract.compiler ?? "unknown"}
                    </Badge>
                    <Badge variant="default">
                      Rules Version: {contract ? `v${contract.contract_version}` : "draft"}
                    </Badge>
                  </div>

                  {/* Progressive disclosure: technical JSON hidden until requested. */}
                  <div className="contract-json-wrap">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setShowContract((v) => !v)}
                      aria-expanded={showContract}
                    >
                      {showContract ? "Hide Transformation Rules" : "View Transformation Rules"}
                    </Button>
                    {showContract && (
                      <JsonViewer
                        value={contract ?? draftContract}
                        filename="transformation-contract.json"
                      />
                    )}
                  </div>
                </>
              )}

              {!draftContract && (
                <p className="wizard-field__help">
                  Generate transformation rules to review the keys, compare fields, and steps used to
                  align your data.
                </p>
              )}
            </section>
          )}

          {/* Relocated inline shadow preview + approval + Run (contract engine
              only). Renders nothing until the contract is approved. */}
          {!useScriptTransformations && <ShadowPreviewPanel />}
        </>
      )}
    </StepShell>
  );
}

export default TransformationSpecStep;
