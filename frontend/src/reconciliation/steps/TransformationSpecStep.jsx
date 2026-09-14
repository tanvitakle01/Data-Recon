import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import {
  appendDatasetSide,
  buildMappingSheetPayload,
  cleanAggregationRules,
  gate2SampleRows,
  mergeGeneratedMapping,
  rebuildMapping,
} from "../lib/payload";
import { detectFieldRole } from "../lib/fieldRoleAliases";
import StepShell from "../components/StepShell";
import MappingEditor from "../components/MappingEditor";
import TransformationPreviewPanel from "../components/TransformationPreviewPanel";
import TransformationsDrawer from "../components/TransformationsDrawer";
import { operationsToSteps, serializeOperations } from "../lib/transformationsModel";
import { Button, Alert } from "@bristlecone/canopy";
import { SlidersHorizontal } from "lucide-react";

function TransformationSpecStep() {
  const { state, dispatch } = useWizard();
  const { source, target, comparisonType, transformationSpec } = state;
  const {
    parsedMappingSheet,
    aggregationRules,
    transformations,
    mapping,
    mappingResolution,
    contract,
    useScriptTransformations,
  } = transformationSpec;

  const sourceColumns = useMemo(() => source.dataset?.columns ?? [], [source.dataset]);
  const targetColumns = useMemo(() => target.dataset?.columns ?? [], [target.dataset]);
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState(null);
  const [mappingResolutionLoading, setMappingResolutionLoading] = useState(false);
  const [mappingResolutionError, setMappingResolutionError] = useState(null);
  // Non-blocking notice from the inference call: a provider-failover message
  // (served by OpenAI) or a degraded reason (no mapping could be generated).
  const [mapNotice, setMapNotice] = useState(null);
  const [contractError, setContractError] = useState(null);
  // Non-blocking notice when an LLM provider failover occurred (Groq→OpenAI) or
  // when every AI provider was unavailable (spec points 5 & 6).
  const [providerNotice, setProviderNotice] = useState(null);
  const [approveLoading, setApproveLoading] = useState(false);
  // The Transformations Editor lives entirely in a right-side slide-out drawer,
  // opened from the floating launcher — closed by default so the step opens on
  // the field mapping.
  const [editorOpen, setEditorOpen] = useState(false);
  // Signature of the (source, target) datasets we last auto-mapped. When the
  // user re-uploads, the dataset id changes and the reducer clears the stale
  // mapping, so a new signature re-triggers auto-mapping against the fresh
  // columns — no restart needed.
  const mappedSignatureRef = useRef(null);

  const datasetSignature = (src, tgt) =>
    `${src?.dataset?.datasetId ?? src?.dataset?.fetchedAt ?? ""}::` +
    `${tgt?.dataset?.datasetId ?? tgt?.dataset?.fetchedAt ?? ""}`;

  // Feature flag (USE_SCRIPT_TRANSFORMATIONS): fetched once to decide whether
  // the script-transformation flow (TransformationPreviewPanel) is available
  // alongside the transformations/mapping flow below.
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

  // ── LLM-inferred field mapping ────────────────────────────────────────────
  // Infers the source→target FIELD mapping (column→column + Key/Compare role)
  // from a sample of the uploaded data, via the Groq→OpenAI failover client.
  // FIELD mapping only. `preserveEdits` keeps rows the user hand-edited and
  // refreshes only the untouched generated ones (Regenerate); the first run
  // replaces.
  const runInference = useCallback(async ({ preserveEdits = false, forceLlm = false } = {}) => {
    if (!source.dataset || !target.dataset) return;

    const formData = new FormData();
    const okSource = appendDatasetSide(formData, "source", source);
    const okTarget = appendDatasetSide(formData, "target", target);
    if (!okSource || !okTarget) {
      setMapError("Source or target data is no longer available. Go back and re-upload it.");
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
  // and no mapping yet — including after a re-upload, which changes the dataset
  // signature. Deferred with a timeout so the fetch (and its setState) doesn't
  // run synchronously inside the effect body.
  useEffect(() => {
    if (mapping) return;
    if (!source.dataset || !target.dataset) return;
    const signature = datasetSignature(source, target);
    if (mappedSignatureRef.current === signature) return;
    mappedSignatureRef.current = signature;
    const id = setTimeout(() => runInference({ preserveEdits: false }), 0);
    return () => clearTimeout(id);
  }, [mapping, source, target, runInference]);

  // ── Sequential AI mapping resolution (mapping-sheet-driven) ──────────────
  // Only runs when a mapping sheet was uploaded. Four chained LLM calls
  // (relevant fields -> enriched fields -> transformation chain ->
  // deterministic operations) run server-side against ONLY the real
  // source/target header bindings. Never touches business_key/compare_fields
  // (Mapping Editor's job).
  const resolvedMappingSignatureRef = useRef(null);

  const runMappingResolution = useCallback(async () => {
    if (!parsedMappingSheet || !source.dataset || !target.dataset) return;
    setMappingResolutionLoading(true);
    setMappingResolutionError(null);
    try {
      const res = await api.post("/api/recon/mapping-resolution/resolve", {
        mapping_sheet: parsedMappingSheet,
        source_columns: sourceColumns,
        target_columns: targetColumns,
      });
      const result = res.data ?? null;
      // Seed the Transformations Editor ONLY the first time — once it has any
      // steps (AI-seeded or hand-built), a re-resolve (e.g. after a dataset
      // change) must never silently overwrite a human's edits. The editor stays
      // the editable override layer either way.
      let steps = null;
      if ((transformations ?? []).length === 0 && (result?.operations ?? []).length > 0) {
        const catalogueRes = await api.get("/api/recon/operations");
        const catalogue = (catalogueRes.data?.operations ?? []).filter((o) => o.kind !== "compare");
        steps = operationsToSteps(result.operations, catalogue);
      }
      if (steps && steps.length) {
        dispatch({ type: WizardActions.SET_TRANSFORMATIONS, transformations: steps });
      }
      dispatch({ type: WizardActions.SET_MAPPING_RESOLUTION, mappingResolution: result });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setMappingResolutionError(typeof detail === "string" ? detail : "Mapping resolution failed.");
    } finally {
      setMappingResolutionLoading(false);
    }
  }, [parsedMappingSheet, source, target, sourceColumns, targetColumns, transformations, dispatch]);

  useEffect(() => {
    if (mappingResolution) return;
    if (!parsedMappingSheet || !source.dataset || !target.dataset) return;
    // Keyed on the dataset pair AND the sheet itself — the reducer nulls
    // `mappingResolution` on either a dataset change or a new/removed mapping
    // sheet, but the dataset signature alone wouldn't change on a sheet swap,
    // which would otherwise block re-firing for the new sheet's content.
    const signature =
      `${datasetSignature(source, target)}::` +
      `${parsedMappingSheet.sheet_name ?? ""}::${parsedMappingSheet.row_count ?? ""}`;
    if (resolvedMappingSignatureRef.current === signature) return;
    resolvedMappingSignatureRef.current = signature;
    const id = setTimeout(() => runMappingResolution(), 0);
    return () => clearTimeout(id);
  }, [mappingResolution, parsedMappingSheet, source, target, runMappingResolution]);

  // ── contract lifecycle: validate → approve ────────────────────────────────
  const validateDraft = useCallback(
    async (draft) => {
      // A properly-sized sample (not the small upload-preview array) so Gate 2
      // sees enough rows for a genuinely selective filter/business rule to have
      // a realistic chance of matching something — see gate2SampleRows.
      const [sourceSample, targetSample] = await Promise.all([
        gate2SampleRows(source),
        gate2SampleRows(target),
      ]);
      const res = await api.post("/api/recon/contracts/validate", {
        draft,
        source_columns: source.dataset?.columns ?? [],
        target_columns: target.dataset?.columns ?? [],
        source_sample: sourceSample,
        target_sample: targetSample,
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

  // Optional AI convenience: turn a plain-language description into steps by
  // reusing the SAME Groq compile entry point. Returns the drafted operations
  // for the Transformations Editor to append (nothing is auto-applied).
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

  // The DraftContract this page authors: the transformation operations + the
  // human-owned field mapping + structured aggregation rules — exactly the
  // shape /compile would return. `value_mappings` is always empty: this deploy
  // is mapping-sheet-driven only, so no data-level value pairing runs.
  const buildDraft = () => ({
    comparison_type: comparisonType?.id ?? "custom",
    source_type: source.kind ?? "excel",
    target_type: target.kind ?? "excel",
    operations: serializeOperations(transformations ?? []),
    aggregation_rules: cleanAggregationRules(aggregationRules),
    business_key: mappingKeyFields(),
    compare_fields: mappingCompareFields(),
    value_mappings: [],
    source_schema: source.dataset?.columns ?? [],
    target_schema: target.dataset?.columns ?? [],
    options: { case_insensitive: true, trim_whitespace: true },
    compiler: "transformations",
  });

  // Single CTA: validate the draft (Gate 1/2), then approve it. Gate internals
  // stay hidden; only a concise error surfaces if validation fails. Approval is
  // the gate Results depends on — Continue only advances once this succeeds.
  const approveTransformations = async () => {
    if (!source.dataset || !target.dataset) return;
    setApproveLoading(true);
    setContractError(null);
    setProviderNotice(null);
    try {
      const draft = buildDraft();
      dispatch({ type: WizardActions.SET_DRAFT_CONTRACT, draftContract: draft });
      const report = await validateDraft(draft);
      if (!report?.ok) {
        const firstError =
          report?.gate1?.errors?.[0] ||
          report?.gate2?.errors?.[0] ||
          "These transformation steps aren't valid yet — review them and try again.";
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
  // mapping is confirmed (Gate 1 requires ≥1 business key). Zero transformation
  // steps is valid — it reconciles the raw source against the target.
  const canApprove =
    Boolean(source.dataset && target.dataset) &&
    (mapping?.mapping?.key_fields?.length ?? 0) > 0;

  // Editing the steps/aggregations after approval invalidates the prior
  // approval so Approve re-enables for the changed steps.
  const invalidateApproval = () => {
    if (contract) dispatch({ type: WizardActions.SET_DRAFT_CONTRACT, draftContract: null });
  };

  // Continue advances to Results, which compiles/runs the approved contract
  // (see ReconciliationRunStep) — so it's gated on having one, same as the
  // script-transformation flow is gated on its own approval.
  const canContinueStep = useScriptTransformations ? true : Boolean(contract);

  const stepCount = (transformations ?? []).length;

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

      {/* Viewport-pinned launcher for the Transformations Editor drawer — the
          only route to the editor, so it stays reachable however far the field
          mapping above has been scrolled. */}
      <button
        type="button"
        className="ct-transformations-fab"
        aria-expanded={editorOpen}
        onClick={() => setEditorOpen(true)}
      >
        <SlidersHorizontal size={15} aria-hidden />
        Transformations
        <span className="ct-transformations-fab__hint">
          {mappingResolutionLoading
            ? "Resolving…"
            : `${stepCount} step${stepCount === 1 ? "" : "s"}`}
        </span>
      </button>

      <TransformationsDrawer
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        steps={transformations ?? []}
        sourceColumns={sourceColumns}
        onDraftSteps={draftStepsFromDescription}
        onChange={(next) => {
          dispatch({ type: WizardActions.SET_TRANSFORMATIONS, transformations: next });
          invalidateApproval();
        }}
      >
        <p className="wizard-field__help" style={{ marginTop: 0 }}>
          Build an ordered list of transformation steps — each step is one operation applied to
          the source before it is reconciled against the target. Drag to reorder within a phase
          (Filters → Transforms → Aggregations).
        </p>
        {mappingResolutionLoading && (
          <p className="wizard-field__help">Resolving the mapping sheet into transformation steps…</p>
        )}
        {mappingResolutionError && <Alert variant="error">{mappingResolutionError}</Alert>}
        {mappingResolution?.degraded && mappingResolution?.degraded_reason && (
          <Alert variant="info">{mappingResolution.degraded_reason}</Alert>
        )}
        {(mappingResolution?.proposed_operations ?? []).length > 0 && (
          <Alert variant="warning" style={{ marginBottom: 12 }}>
            <strong>New operation(s) proposed for review — not yet added:</strong>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {mappingResolution.proposed_operations.map((p, idx) => (
                <li key={`${p.name}-${idx}`}>
                  <code>{p.name}</code> ({p.kind}) — {p.contract}
                  {p.flagged_for_shadow_test ? " — flagged for a shadow-mode test before promotion" : ""}
                </li>
              ))}
            </ul>
          </Alert>
        )}
        {(mappingResolution?.requires_value_pairing ?? []).length > 0 && (
          <Alert variant="warning" style={{ marginBottom: 12 }}>
            <strong>
              These fields need value-level pairing, which this deploy does not run — map them
              with a transformation step instead:
            </strong>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {mappingResolution.requires_value_pairing.map((f, idx) => (
                <li key={`${f.source_column}-${idx}`}>
                  <code>{f.source_column}</code>
                  {f.description ? ` — ${f.description}` : ""}
                </li>
              ))}
            </ul>
          </Alert>
        )}
      </TransformationsDrawer>

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
                  ? "✓ Transformations Approved"
                  : "Approve Transformations"}
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
