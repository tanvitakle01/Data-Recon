import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import {
  appendDatasetSide,
  buildMappingSheetPayload,
  buildValueMappingFormData,
  cleanAggregationRules,
  fullOrPreviewRows,
  keyFieldPairs,
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
import MappingReviewDrawer from "../components/MappingReviewDrawer";
import { serializeOperations } from "../lib/recipeModel";
import { Button, Alert } from "@bristlecone/canopy";

// Distinct-VALUE summary of the AI-mapping (value-pairing) run, across every
// paired key pair — mirrors MappingReviewBody's own splitMatches so the two
// surfaces never disagree. A source value with two accepted candidates is
// one matched value, not two.
function summarizePairing(valueMappings) {
  if (!valueMappings) return null;
  const sides = valueMappings;
  const matchedValues = new Set();
  const unmatchedValues = new Set();
  for (const side of sides) {
    for (const m of side?.matches ?? []) {
      if (m.target_value != null) matchedValues.add(m.source_value);
      else unmatchedValues.add(m.source_value);
    }
  }
  const matched = matchedValues.size;
  const total = matched + unmatchedValues.size;
  return { matched, total };
}

// Merges a fresh, LLM-free live-prepass result into the current valueMappings
// side, per source_value — never regressing a value that a real "Run
// AI-mapping" already resolved via the LLM back down to "unpaired" or a
// cheaper match. ValueMatch.rule already encodes provenance:
// "value_pairing.identity"/"library_reused" are cheap/deterministic (safe to
// recompute every time); "llm_verified"/"pattern_reused" required an actual
// LLM call, so those are preserved verbatim. A value the recipe edit changed
// or removed simply won't appear under its old identity in `fresh` — that's
// correct, not a regression, since that exact string no longer exists.
function mergeLivePrepass(prevMapping, freshMapping) {
  if (!freshMapping) return prevMapping ?? null;
  const prevByValue = new Map((prevMapping?.matches ?? []).map((m) => [m.source_value, m]));
  const merged = freshMapping.matches.map((fresh) => {
    const prev = prevByValue.get(fresh.source_value);
    const prevWasLlmDerived = prev && /llm_verified|pattern_reused/.test(prev.rule);
    return prevWasLlmDerived ? prev : fresh;
  });
  return { ...freshMapping, matches: merged };
}

// Same idea as mergeLivePrepass, but across the whole array of value
// mappings, matched by (source_field, target_field) identity rather than
// array position — a mid-edit recipe can change how many/which pairs come
// back, so position isn't stable. A previous pair the fresh response no
// longer covers (e.g. a column momentarily dropped mid-edit) is kept as-is
// rather than discarded.
function mergePrepassArray(prevMappings, freshMappings) {
  const pairKey = (vm) => `${vm.source_field}->${vm.target_field}`;
  const prev = prevMappings ?? [];
  const fresh = freshMappings ?? [];
  const prevByKey = new Map(prev.map((vm) => [pairKey(vm), vm]));
  const freshKeys = new Set();
  const merged = fresh.map((freshVm) => {
    freshKeys.add(pairKey(freshVm));
    return mergeLivePrepass(prevByKey.get(pairKey(freshVm)), freshVm);
  });
  for (const vm of prev) {
    if (!freshKeys.has(pairKey(vm))) merged.push(vm);
  }
  return merged;
}

function TransformationSpecStep() {
  const { state, dispatch } = useWizard();
  const { source, target, comparisonType, transformationSpec } = state;
  const {
    parsedMappingSheet,
    aggregationRules,
    recipe,
    mapping,
    valueMappings,
    contract,
    useScriptTransformations,
  } = transformationSpec;

  const sourceColumns = useMemo(() => source.dataset?.columns ?? [], [source.dataset]);
  const targetColumns = useMemo(() => target.dataset?.columns ?? [], [target.dataset]);
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
  // Mapping Review: closed by default, opens as a right-side slide-out drawer
  // that overlays the Recipe Editor rather than replacing it in place.
  const [reviewOpen, setReviewOpen] = useState(false);
  // Signature of the (source, target) datasets we last auto-mapped. When the
  // user re-uploads or re-fetches, the dataset id changes and the reducer
  // clears the stale mapping, so a new signature re-triggers auto-mapping
  // against the fresh columns — no restart needed.
  const mappedSignatureRef = useRef(null);

  const datasetSignature = (src, tgt) =>
    `${src?.dataset?.datasetId ?? src?.dataset?.fetchedAt ?? ""}::` +
    `${tgt?.dataset?.datasetId ?? tgt?.dataset?.fetchedAt ?? ""}`;

  // Feature flag (USE_SCRIPT_TRANSFORMATIONS): fetched once to decide whether
  // the script-transformation flow (TransformationPreviewPanel) is available
  // alongside the recipe/AI-mapping flow below.
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
    const okSource = appendDatasetSide(formData, "source", source);
    const okTarget = appendDatasetSide(formData, "target", target);
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
          // ("Generated via Vector Library" vs "Generated via Azure AI Foundry").
          origin: {
            source: data.source ?? null,
            provider: data.provider ?? null,
            version: data.library_version ?? null,
            confidence: data.confidence ?? null,
          },
        },
      });
      // Surface a degraded reason (nothing generated) or a provider notice
      // without blocking — the table is still usable.
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

  // ── AI value pairing (every confirmed Key field pair) ─────────────────────
  const missingValueMappingReqs = useMemo(
    () => missingValueMappingRequirements(mapping?.display),
    [mapping],
  );
  const canRunValueMapping =
    Boolean(source.dataset && target.dataset) && missingValueMappingReqs.length === 0;
  const pairing = useMemo(() => summarizePairing(valueMappings), [valueMappings]);

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
        valueMappings: res.data?.pairs ?? [],
      });
      setValueMappingSuccess(true);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setValueMappingError(typeof detail === "string" ? detail : "AI-mapping failed.");
    } finally {
      setValueMappingLoading(false);
    }
  };

  // ── live, LLM-free pairing pre-pass ────────────────────────────────────────
  // Keeps Mapping Review current as the recipe changes, without ever
  // triggering an LLM call — only the "Run AI-mapping" button above does
  // that. Runs the CURRENT recipe (filters/transforms only — the backend
  // drops any aggregate op) against the FULL current source dataset, then
  // resolves values via library lookup + identity match only. A ref (not a
  // dependency) tracks the latest valueMappings so the merge always has the
  // current baseline without making this effect depend on its own output.
  const liveSourceRows = useMemo(() => fullOrPreviewRows(source), [source]);
  const liveTargetRows = useMemo(() => fullOrPreviewRows(target), [target]);
  const valueMappingsRef = useRef(valueMappings);
  useEffect(() => {
    valueMappingsRef.current = valueMappings;
  }, [valueMappings]);
  const livePrepassTimerRef = useRef(null);

  useEffect(() => {
    if (livePrepassTimerRef.current) clearTimeout(livePrepassTimerRef.current);
    if (!canRunValueMapping) return;
    const pairs = keyFieldPairs(mapping?.display);
    if (pairs.length === 0) return;

    let cancelled = false;
    livePrepassTimerRef.current = setTimeout(async () => {
      try {
        const res = await api.post("/api/recon/value-mapping/live-prepass", {
          source_rows: liveSourceRows,
          target_rows: liveTargetRows,
          operations: serializeOperations(recipe ?? []),
          source_schema: sourceColumns,
          target_schema: targetColumns,
          comparison_type: comparisonType?.id ?? "custom",
          source_connector: source.kind ?? "excel",
          target_connector: target.kind ?? "excel",
          key_pairs: pairs,
        });
        if (cancelled) return;
        const prev = valueMappingsRef.current;
        dispatch({
          type: WizardActions.SET_VALUE_MAPPINGS,
          valueMappings: mergePrepassArray(prev, res.data?.pairs),
        });
      } catch {
        // Best-effort live feedback only — a transient failure here never
        // blocks the recipe editor or a real "Run AI-mapping".
      }
    }, 400);
    return () => {
      cancelled = true;
      if (livePrepassTimerRef.current) clearTimeout(livePrepassTimerRef.current);
    };
  }, [
    recipe,
    mapping,
    liveSourceRows,
    liveTargetRows,
    sourceColumns,
    targetColumns,
    canRunValueMapping,
    comparisonType,
    source.kind,
    target.kind,
    dispatch,
  ]);

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
  const keyFieldNames = useMemo(
    () => mappingKeyFields().map((f) => f.source_field),
    [mappingKeyFields],
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

  // The DraftContract this page authors: recipe operations + the human-owned
  // field mapping + structured aggregation rules + whatever AI-mapping has
  // resolved so far — exactly the shape /compile would return. The executor
  // runs operations (filters/transforms) BEFORE value_mappings (see
  // engine.executor.build_shadow_source), so the recipe pre-processes the raw
  // values and value-pairing resolves whatever it produces.
  const buildRecipeDraft = () => ({
    comparison_type: comparisonType?.id ?? "custom",
    source_type: source.kind ?? "excel",
    target_type: target.kind ?? "excel",
    operations: serializeOperations(recipe ?? []),
    aggregation_rules: cleanAggregationRules(aggregationRules),
    business_key: mappingKeyFields(),
    compare_fields: mappingCompareFields(),
    value_mappings: valueMappings ?? [],
    source_schema: source.dataset?.columns ?? [],
    target_schema: target.dataset?.columns ?? [],
    options: { case_insensitive: true, trim_whitespace: true },
    compiler: "recipe",
  });

  // Single CTA covering the combined recipe + AI-pairing state: validate the
  // draft (Gate 1/2), then approve it. Gate internals stay hidden; only a
  // concise error surfaces if validation fails. Approval is the gate Results
  // depends on — Continue only advances once this succeeds.
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

  // Editing the recipe/aggregations after approval invalidates the prior
  // approval so Approve re-enables for the changed steps.
  const invalidateApproval = () => {
    if (contract) dispatch({ type: WizardActions.SET_DRAFT_CONTRACT, draftContract: null });
  };

  // Continue advances to Results, which compiles/runs the approved contract
  // (see ReconciliationRunStep) — so it's gated on having one, same as the
  // script-transformation flow is gated on its own approval.
  const canContinueStep = useScriptTransformations ? true : Boolean(contract);

  return (
    <StepShell stepKey="transformationSpec" canContinue={canContinueStep}>
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

      <div className="ct-kpi-grid">
        <div className="ct-kpi-card">
          <p className="ct-kpi-card__label">Columns mapped</p>
          <div className="ct-kpi-card__row">
            <span className="ct-kpi-card__value">{mapping?.display?.length ?? 0}</span>
          </div>
        </div>
        <div className="ct-kpi-card">
          <p className="ct-kpi-card__label">Key fields</p>
          <div className="ct-kpi-card__row">
            <span className="ct-kpi-card__value">{keyFieldNames.length}</span>
            {keyFieldNames.length > 0 && (
              <span className="ct-kpi-card__sub">{keyFieldNames.join(", ")}</span>
            )}
          </div>
        </div>
        {pairing && (
          <div className="ct-kpi-card">
            <p className="ct-kpi-card__label">Values paired</p>
            <div className="ct-kpi-card__row">
              <span
                className="ct-kpi-card__value"
                style={{ color: pairing.total ? "var(--bcone-orange)" : "var(--ink)" }}
              >
                {pairing.total ? `${Math.round((pairing.matched / pairing.total) * 100)}%` : "—"}
              </span>
              <span className="ct-kpi-card__sub">
                {pairing.matched} of {pairing.total}
              </span>
            </div>
          </div>
        )}
      </div>

      <section className="ct-card">
        <div className="ct-card__head">
          <h3 className="ct-card__title">Value pairing</h3>
        </div>
        <div className="ct-card__body">
          <p className="wizard-field__help" style={{ marginTop: 0 }}>
            {pairing
              ? pairing.total > 0
                ? `${pairing.matched} of ${pairing.total} distinct values paired (${Math.round((pairing.matched / pairing.total) * 100)}%). ${pairing.total - pairing.matched} value${pairing.total - pairing.matched === 1 ? "" : "s"} have no target and will be reported as mismatches.`
                : "AI-mapping ran but found no distinct values to pair yet."
              : "Run AI-mapping to pair distinct source values (e.g. Material, Plant) against the target — reflects the recipe's current output."}
          </p>
          <Button
            type="button"
            variant="primary"
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
            style={{ width: "100%" }}
          >
            {valueMappingLoading ? "Matching…" : valueMappings ? "Re-run AI-mapping" : "Run AI-mapping"}
          </Button>
          {valueMappingError && <Alert variant="error">{valueMappingError}</Alert>}
          {valueMappingSuccess && !valueMappingError && (
            <Alert variant="success">
              AI-mapping complete. Expand Mapping Review below to inspect the tiers.
            </Alert>
          )}
        </div>
      </section>

      <button
        type="button"
        className="ct-mapping-review-fab"
        aria-expanded={reviewOpen}
        onClick={() => setReviewOpen(true)}
      >
        Mapping Review
        <span className="ct-mapping-review-fab__hint">
          {pairing ? `${pairing.matched}/${pairing.total} paired` : "Inspect values"}
        </span>
      </button>

      <section className="wizard-section">
        <h3 className="wizard-section__title">Transformation Recipe</h3>
        <p className="wizard-field__help">
          Build an ordered list of transformation steps — each step is one operation applied to
          the source before AI-mapping pairs the resulting values. Drag to reorder within a phase
          (Filters → Transforms → Aggregations).
        </p>
        <RecipeEditor
          steps={recipe ?? []}
          onChange={(next) => {
            dispatch({ type: WizardActions.SET_RECIPE, recipe: next });
            invalidateApproval();
          }}
          sourceColumns={sourceColumns}
          onDraftSteps={draftStepsFromDescription}
        />
      </section>

      <MappingReviewDrawer open={reviewOpen} onClose={() => setReviewOpen(false)} />

      {useScriptTransformations && <TransformationPreviewPanel />}

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
    </StepShell>
  );
}

export default TransformationSpecStep;
