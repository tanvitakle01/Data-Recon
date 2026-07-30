import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import {
  appendDatasetSide,
  buildMappingSheetPayload,
  buildValueMappingFormData,
  cleanAggregationRules,
  mergeGeneratedMapping,
  missingValueMappingRequirements,
  rebuildMapping,
  sampleRows,
} from "../lib/payload";
import { detectFieldRole } from "../lib/fieldRoleAliases";
import StepShell from "../components/StepShell";
import MappingEditor from "../components/MappingEditor";
import RecipeEditor from "../components/RecipeEditor";
import TransformationPreviewPanel from "../components/TransformationPreviewPanel";
import ShadowPreviewPanel from "../components/ShadowPreviewPanel";
import { serializeOperations } from "../lib/recipeModel";
import { Button, Alert } from "@bristlecone/canopy";

function TransformationSpecStep() {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();
  const { source, target, comparisonType, transformationSpec } = state;
  const {
    mappingMode,
    parsedMappingSheet,
    aggregationRules,
    recipe,
    mapping,
    valueMappings,
    contract,
    useScriptTransformations,
  } = transformationSpec;

  const setMappingMode = (mode) =>
    dispatch({ type: WizardActions.SET_MAPPING_MODE, mappingMode: mode });

  const sourceColumns = useMemo(() => source.dataset?.columns ?? [], [source.dataset]);
  const targetColumns = useMemo(() => target.dataset?.columns ?? [], [target.dataset]);
  // Stable identities so the recipe's live preview only refetches on a real
  // change (recipe/selection/data), not on every unrelated parent re-render.
  const sourceSample = useMemo(() => sampleRows(source), [source]);
  const recipePreviewContext = useMemo(
    () => ({
      comparison_type: comparisonType?.id ?? "custom",
      source_type: source.kind ?? "excel",
      target_type: target.kind ?? "excel",
      target_schema: targetColumns,
    }),
    [comparisonType, source.kind, target.kind, targetColumns],
  );
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState(null);
  // Non-blocking notice from the inference call: a provider-failover message
  // (served by OpenAI) or a degraded reason (no mapping could be generated).
  const [mapNotice, setMapNotice] = useState(null);
  const [valueMappingLoading, setValueMappingLoading] = useState(false);
  const [valueMappingError, setValueMappingError] = useState(null);
  const [valueMappingSuccess, setValueMappingSuccess] = useState(false);
  const [contractError, setContractError] = useState(null);
  // Non-blocking notice when an LLM provider failover occurred (Groq→OpenAI) or
  // when every AI provider was unavailable (spec points 5 & 6).
  const [providerNotice, setProviderNotice] = useState(null);
  const [approveLoading, setApproveLoading] = useState(false);
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
      // Tag each row with the canonical business-field role its header(s)
      // match (Product/Location/Date/Quantity) — same detection used for a
      // manually-added row in MappingEditor — so Deterministic Mapping can
      // resolve them by role instead of by a hardcoded literal column name.
      const inferred = (data.display ?? []).map((row) => ({
        ...row,
        field_role: row.field_role ?? detectFieldRole(row.source_col, row.target_col),
      }));
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
    const formData = buildValueMappingFormData(source, target, parsedMappingSheet, mapping?.display);
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
        },
      });
      setValueMappingSuccess(true);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setValueMappingError(typeof detail === "string" ? detail : "AI-mapping failed.");
    } finally {
      setValueMappingLoading(false);
    }
  };

  // ── deterministic reconciliation (Flow 1) ─────────────────────────────────
  // Deterministic Mapping no longer compiles/runs a contract inline on this
  // step — Continue takes the user to the Results step, which compiles,
  // approves, and runs the deterministic contract there (see
  // ReconciliationRunStep). This just gates Continue on the mapping being done.
  const canRunDeterministicRecon = Boolean(valueMappings) && missingValueMappingReqs.length === 0;

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

  // The confirmed field mapping (human-owned; never inferred by a compiler).
  const mappingKeyFields = useCallback(
    () =>
      (mapping?.mapping?.key_fields ?? []).map((f) => ({
        source_field: f.source_col,
        target_field: f.target_col,
      })),
    [mapping],
  );
  const mappingCompareFields = useCallback(
    () =>
      (mapping?.mapping?.compare_fields ?? []).map((f) => ({
        source_field: f.source_col,
        target_field: f.target_col,
      })),
    [mapping],
  );

  // Optional AI convenience: turn a plain-language description into recipe steps
  // by reusing the SAME Groq compile entry point. Returns the drafted
  // operations for RecipeEditor to append (nothing is auto-applied).
  const draftStepsFromDescription = useCallback(
    async (description) => {
      const payload = {
        mapping_sheet: buildMappingSheetPayload(parsedMappingSheet, mapping),
        // The whole description is handed to the compiler as free-text rules;
        // Groq drafts operations from it (deterministic stub only covers a few
        // phrasings — if no AI is configured the user just builds steps by hand).
        rules: description,
        transformation_rules: [],
        matching_rules: [],
        filter_rules: [],
        aggregation_rules: [],
        business_key: mappingKeyFields(),
        compare_fields: mappingCompareFields(),
        value_mappings: [],
        source_schema: source.dataset?.columns ?? [],
        target_schema: target.dataset?.columns ?? [],
        comparison_type: comparisonType?.id ?? "custom",
        source_type: source.kind ?? "excel",
        target_type: target.kind ?? "excel",
        actor: "wizard-user",
      };
      const res = await api.post("/api/recon/contracts/compile", payload);
      setProviderNotice(res.data?.provider_notice ?? null);
      return res.data?.draft?.operations ?? [];
    },
    [parsedMappingSheet, mapping, source, target, comparisonType, mappingKeyFields, mappingCompareFields],
  );

  // The DraftContract the recipe authors: operations straight from the recipe
  // (no compiler runs) + the human-owned field mapping + structured aggregation
  // rules — exactly the shape /compile would return.
  const buildRecipeDraft = () => ({
    comparison_type: comparisonType?.id ?? "custom",
    source_type: source.kind ?? "excel",
    target_type: target.kind ?? "excel",
    operations: serializeOperations(recipe ?? []),
    aggregation_rules: cleanAggregationRules(aggregationRules),
    business_key: mappingKeyFields(),
    compare_fields: mappingCompareFields(),
    // Manual flow never applies deterministic value mappings — those belong to
    // the Deterministic flow.
    value_mappings: [],
    source_schema: source.dataset?.columns ?? [],
    target_schema: target.dataset?.columns ?? [],
    options: { case_insensitive: true, trim_whitespace: true },
    compiler: "recipe",
  });

  // Single CTA for the Manual contract flow: validate the recipe-authored draft
  // (Gate 1/2), then approve it — which hands off to the existing shadow-curtain
  // approval flow (ShadowPreviewPanel keys off the approved contract). Gate
  // internals stay hidden; only a concise error surfaces if validation fails.
  const approveTransformations = async () => {
    if (!source.dataset || !target.dataset) return;
    setApproveLoading(true);
    setContractError(null);
    setProviderNotice(null);
    try {
      const draft = buildRecipeDraft();
      dispatch({ type: WizardActions.SET_DRAFT_CONTRACT, draftContract: draft });
      const report = await validateDraft(draft);
      if (!report?.ok) {
        const firstError =
          report?.gate1?.errors?.[0] ||
          report?.gate2?.errors?.[0] ||
          "These transformation steps aren't valid yet — review the recipe and try again.";
        setContractError(firstError);
        return;
      }
      const res = await api.post("/api/recon/contracts/approve", {
        draft,
        approved_by: "wizard-user",
      });
      dispatch({ type: WizardActions.SET_APPROVED_CONTRACT, contract: res.data?.contract });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setContractError(typeof detail === "string" ? detail : "Approval failed.");
    } finally {
      setApproveLoading(false);
    }
  };

  // Approve is enabled once both datasets are loaded and at least one Key field
  // mapping is confirmed (Gate 1 requires ≥1 business key). A recipe with zero
  // steps is valid — it reconciles the raw source against the target.
  const canApprove =
    Boolean(source.dataset && target.dataset) &&
    (mapping?.mapping?.key_fields?.length ?? 0) > 0;

  // The run happens inline on this page only for the Manual contract flow (via
  // ShadowPreviewPanel), so the generic Continue is hidden there — advancement
  // is via "Run Reconciliation". Deterministic Mapping and the Manual script
  // flow both advance to Results via Continue — the run itself (and, for
  // Deterministic, the contract compile/approve) happens on the Results step.
  const runsInline = mappingMode === "manual" && !useScriptTransformations;
  const hideContinue = mappingMode === null || runsInline;
  // Deterministic Mapping must have a completed value-mapping run before
  // Continue advances to Results (Results compiles the contract from it).
  const canContinueStep = mappingMode === "deterministic" ? canRunDeterministicRecon : true;

  return (
    <StepShell
      stepKey="transformationSpec"
      canContinue={canContinueStep}
      hideContinue={hideContinue}
    >
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
                Field mapping · transformation recipe · reviewed shadow preview
              </span>
            </button>
            <button
              type="button"
              className="wizard-option-card"
              onClick={() => setMappingMode("deterministic")}
            >
              <span className="wizard-option-card__label">AI-mapping</span>
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
          Field mapping + Run Deterministic Mapping + View Mapping Review only.
          Continue advances to Results, where the contract is compiled,
          approved, and run. No mapping sheet, rules, transformations,
          aggregation, or transformation-rules approval block. */}
      {mappingMode === "deterministic" && (
        <>
          <section className="wizard-section">
            <h3 className="wizard-section__title">Field Mapping</h3>
            <p className="wizard-field__help">
              Confirm the source-to-target field mapping used for AI-mapping. Each row's
              "Business Field" is auto-detected from the column names (e.g. "SKU" or "Material Code" →
              Product / Material) — tag it manually if a required field isn't recognized. AI-mapping
              needs a Product/Material and Plant/Location pair confirmed as Key, plus a
              Date/Period pair as Key and a Quantity pair as Compare.
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
                    ? "Tag a field mapping row as these Business Fields first: " +
                      missingValueMappingReqs
                        .map((r) => `${r.label} (${r.requiredRowRole === "key" ? "Key" : "Compare"})`)
                        .join("; ")
                    : undefined
                }
              >
                {valueMappingLoading ? "Matching…" : "Run AI-mapping"}
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
            {valueMappingError && (
              <Alert variant="error" style={{ marginTop: 12 }}>{valueMappingError}</Alert>
            )}
            {valueMappingSuccess && !valueMappingError && (
              <Alert variant="success" style={{ marginTop: 12 }}>
                AI-mapping complete. Open "View Mapping Review" to inspect the tiers, or
                continue to run reconciliation on the Results step.
              </Alert>
            )}
          </section>
        </>
      )}

      {/* ── Flow 2: Manual Mapping ─────────────────────────────────────────
          Field mapping → transformation recipe → single Approve CTA → the
          existing shadow-curtain approval. The Transformation Recipe is the
          only place operations are authored (no mapping-sheet upload here, no
          separate aggregation card — both live elsewhere / in the recipe). */}
      {mappingMode === "manual" && (
        <>
          {/* Field Mapping — confirmed FIRST, before authoring any transforms. */}
          <section className="wizard-section">
            <h3 className="wizard-section__title">Field Mapping</h3>
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

          {/* Transformation Recipe — the SOLE authoring surface for operations[]
              (filters, transforms, aggregations), with a live preview. */}
          <section className="wizard-section">
            <h3 className="wizard-section__title">Transformation Recipe</h3>
            <p className="wizard-field__help">
              Build an ordered list of transformation steps — each step is one operation applied to
              the source. Drag to reorder within a phase (Filters → Transforms → Aggregations); the
              live preview shows the dataset after each enabled step. What you see is exactly what runs.
            </p>
            <RecipeEditor
              steps={recipe ?? []}
              onChange={(next) => {
                dispatch({ type: WizardActions.SET_RECIPE, recipe: next });
                // Editing the recipe invalidates a prior approval — reset it so
                // the Approve CTA re-enables for the changed steps.
                if (contract) {
                  dispatch({ type: WizardActions.SET_DRAFT_CONTRACT, draftContract: null });
                }
              }}
              sourceColumns={sourceColumns}
              sourceSample={sourceSample}
              previewContext={recipePreviewContext}
              onDraftSteps={draftStepsFromDescription}
            />
          </section>

          {/* Script-transformation flow keeps its own preview/approval panel. */}
          {useScriptTransformations && <TransformationPreviewPanel />}

          {/* Footer — one primary CTA. No gate diagnostics, no JSON viewer. */}
          {!useScriptTransformations && (
            <section className="wizard-section">
              <div className="contract-actions">
                <Button
                  type="button"
                  variant="primary"
                  size="lg"
                  onClick={approveTransformations}
                  disabled={!canApprove || approveLoading || Boolean(contract)}
                >
                  {approveLoading
                    ? "Approving…"
                    : contract
                      ? "✓ Transformation Rules Approved"
                      : "Approve Transformation Rules"}
                </Button>
              </div>
              {!canApprove && !contract && (
                <p className="wizard-field__help">
                  Confirm at least one Key field mapping above to approve.
                </p>
              )}
              {contractError && (
                <Alert variant="error" style={{ marginTop: 12 }}>{contractError}</Alert>
              )}
              {providerNotice && (
                <Alert variant="info" style={{ marginTop: 12 }}>{providerNotice}</Alert>
              )}
            </section>
          )}

          {/* Inline shadow preview + approval + Run (contract engine only).
              Renders nothing until the contract is approved. */}
          {!useScriptTransformations && <ShadowPreviewPanel />}
        </>
      )}
    </StepShell>
  );
}

export default TransformationSpecStep;
