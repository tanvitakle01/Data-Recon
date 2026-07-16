import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../services/api";
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
  missingValueMappingRequirements,
  sampleRows,
} from "../lib/payload";
import StepShell from "../components/StepShell";
import MappingEditor from "../components/MappingEditor";
import BusinessRulesBuilder from "../components/BusinessRulesBuilder";
import AggregationRulesBuilder from "../components/AggregationRulesBuilder";
import StatusBadge from "../components/StatusBadge";
import TransformationPreviewPanel from "../components/TransformationPreviewPanel";

const DOC_ACCEPT = ".xlsx,.xls,.csv";

function TransformationSpecStep() {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();
  const { source, target, comparisonType, transformationSpec } = state;
  const {
    mappingSheet,
    parsedMappingSheet,
    transformationRules,
    matchingRules,
    filterRules,
    aggregationRules,
    mapping,
    valueMappings,
    valueMappingsApproved,
    draftContract,
    validation,
    contract,
    useScriptTransformations,
  } = transformationSpec;

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

  // ── auto-mapping (existing heuristic path, unchanged) ─────────────────────
  const runAutomap = useCallback(async () => {
    if (!source.dataset || !target.dataset) return;

    const formData = new FormData();
    // Auto-selected MDT/recommended fields (tracked per dataset by the
    // connector workspaces) are excluded here — before the auto-mapping
    // heuristic ever sees them — so they can't be classified alongside (and
    // positionally zipped against) the fields the user actually picked. They
    // stay in the dataset itself for tracking/validation/approval; only the
    // /automap request omits them.
    const okSource = appendDatasetSide(formData, "source", source, source.dataset?.mdtFields);
    const okTarget = appendDatasetSide(formData, "target", target, target.dataset?.mdtFields);
    if (!okSource || !okTarget) {
      setMapError("Source or target data is no longer available. Go back and re-fetch or re-upload it.");
      return;
    }

    setMapLoading(true);
    setMapError(null);
    try {
      const res = await api.post("/automap", formData);
      dispatch({
        type: WizardActions.SET_TRANSFORMATION_MAPPING,
        mapping: { display: res.data?.display ?? [], mapping: res.data?.mapping ?? null },
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setMapError(typeof detail === "string" ? detail : "Auto-mapping failed.");
    } finally {
      setMapLoading(false);
    }
  }, [source, target, dispatch]);

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
    const id = setTimeout(runAutomap, 0);
    return () => clearTimeout(id);
  }, [mapping, source, target, runAutomap]);

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
        valueMappings: { product: res.data?.product ?? null, location: res.data?.location ?? null },
      });
      setValueMappingSuccess(true);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setValueMappingError(typeof detail === "string" ? detail : "Deterministic mapping failed.");
    } finally {
      setValueMappingLoading(false);
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
      return "Select a comparison type before generating transformation rules.";
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
      // Only attached once a human has approved them on the Mapping Review
      // page — an unapproved run is never silently applied.
      value_mappings: valueMappingsApproved
        ? [valueMappings?.product, valueMappings?.location].filter(Boolean)
        : [],
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

  return (
    <StepShell stepKey="transformationSpec" canContinue>
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
              <span className="doc-upload__badge">✓ {mappingSheet.name}</span>
              <button
                type="button"
                className="wizard-btn wizard-btn--ghost wizard-btn--sm"
                onClick={() => mappingSheetInputRef.current?.click()}
              >
                Replace
              </button>
              <button
                type="button"
                className="wizard-btn wizard-btn--ghost wizard-btn--sm"
                onClick={removeMappingSheet}
              >
                Remove
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="wizard-btn wizard-btn--ghost"
              onClick={() => mappingSheetInputRef.current?.click()}
            >
              Upload Mapping Sheet
            </button>
          )}
          {parseLoading && <span className="wizard-step__hint">Parsing…</span>}
          {parsedMappingSheet && (
            <span className="doc-upload__badge">
              ✓ {parsedMappingSheet.row_count} rows
            </span>
          )}
          {parseError && <p className="wizard-step__error">⚠️ {parseError}</p>}
        </div>
      </section>

      {/* Section B — Rules */}
      <section className="wizard-section">
        <h3 className="wizard-section__title">Rules</h3>
        <p className="wizard-field__help">Configure transformations, matching, filters, and aggregation.</p>
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
          onChange={(rules) =>
            dispatch({ type: WizardActions.SET_AGGREGATION_RULES, rules })
          }
        />
      </section>

      {/* Section C — Mapping */}
      <section className="wizard-section">
        <h3 className="wizard-section__title">Mapping</h3>
        <p className="wizard-field__help">Review source-to-target mappings.</p>
        <MappingEditor
          mapping={mapping}
          targetColumns={targetColumns}
          loading={mapLoading}
          error={mapError}
          onChange={(next) =>
            dispatch({ type: WizardActions.SET_TRANSFORMATION_MAPPING, mapping: next })
          }
          onRegenerate={() => {
            mappedSignatureRef.current = datasetSignature(source, target);
            runAutomap();
          }}
        />

        <div className="contract-actions" style={{ marginTop: 10 }}>
          <button
            type="button"
            className="wizard-btn wizard-btn--ghost"
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
          </button>
          {valueMappings && (
            <button
              type="button"
              className="wizard-btn wizard-btn--ghost wizard-btn--sm"
              onClick={() => navigate("/reconciliation/transformation-spec/mapping-review")}
            >
              {valueMappingsApproved ? "✓ View Mapping Review" : "View Mapping Review"}
            </button>
          )}
        </div>
        {valueMappingError && <p className="wizard-step__error">⚠️ {valueMappingError}</p>}
        {valueMappingSuccess && !valueMappingError && (
          <p className="wizard-step__success">
            ✓ Deterministic mapping complete. Click "View Mapping Review" to review the results.
          </p>
        )}
      </section>

      {/* Section D — Transformation Preview (USE_SCRIPT_TRANSFORMATIONS) or the
          legacy Transformation Contract flow, decided by the backend feature flag. */}
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
          <button
            type="button"
            className="wizard-btn wizard-btn--primary"
            onClick={generateContract}
            disabled={!canGenerate || compileLoading}
          >
            {compileLoading
              ? "Generating…"
              : draftContract
                ? "Regenerate Transformation Rules"
                : "Generate Transformation Rules"}
          </button>
          <button
            type="button"
            className="wizard-btn wizard-btn--primary"
            onClick={approveContract}
            disabled={!draftContract || !validation?.ok || Boolean(contract) || approveLoading}
          >
            {approveLoading
              ? "Approving…"
              : contract
                ? "Transformation Rules Approved"
                : "Approve Transformation Rules"}
          </button>
        </div>

        {contractError && <p className="wizard-step__error">⚠️ {contractError}</p>}

        {providerNotice && (
          <p className="wizard-step__hint">ℹ️ {providerNotice}</p>
        )}

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
              <span className="contract-summary__chip">
                Business Keys: {draftContract.business_key?.length ?? 0}
              </span>
              <span className="contract-summary__chip">
                Compare Fields: {draftContract.compare_fields?.length ?? 0}
              </span>
              <span className="contract-summary__chip">
                Operations: {draftContract.operations?.length ?? 0}
              </span>
              <span className="contract-summary__chip">
                Generation Method: {draftContract.compiler ?? "unknown"}
              </span>
              <span className="contract-summary__chip">
                Rules Version: {contract ? `v${contract.contract_version}` : "draft"}
              </span>
            </div>

            {/* Progressive disclosure: technical JSON hidden until requested. */}
            <div className="contract-json-wrap">
              <button
                type="button"
                className="wizard-btn wizard-btn--ghost wizard-btn--sm"
                onClick={() => setShowContract((v) => !v)}
                aria-expanded={showContract}
              >
                {showContract ? "Hide Transformation Rules" : "View Transformation Rules"}
              </button>
              {showContract && (
                <pre className="contract-json">
                  {JSON.stringify(contract ?? draftContract, null, 2)}
                </pre>
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
    </StepShell>
  );
}

export default TransformationSpecStep;
