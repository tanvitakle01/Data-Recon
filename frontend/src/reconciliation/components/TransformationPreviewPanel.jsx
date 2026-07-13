// Transformation Preview → User Approval (USE_SCRIPT_TRANSFORMATIONS flow).
//
// Core principle: the user approves TRANSFORMED DATA, never code. The
// generated script is an internal artifact — this panel never renders it.
// Lifecycle: generate (Groq → deterministic fallback, never fails outright)
// → preview (sandbox execution snapshot) → approve/reject the preview data.
import { useState } from "react";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import { buildMappingSheetPayload, cleanBusinessRules, hasMappingPayload, sampleRows } from "../lib/payload";
import StatusBadge from "./StatusBadge";

function ConfidenceBadge({ confidence }) {
  if (confidence == null) return null;
  const pct = Math.round(confidence * 100);
  const tone = confidence >= 0.7 ? "ok" : confidence >= 0.4 ? "pending" : "fail";
  return <span className={`contract-status contract-status--${tone}`}>Confidence: {pct}%</span>;
}

function ModifiedColumnsTable({ columns }) {
  if (!columns?.length) return null;
  return (
    <div className="surface-elevated mapping-editor__table-wrap">
      <table className="table-elevated mapping-editor__table">
        <thead>
          <tr>
            <th>Column</th>
            <th>Change</th>
            <th>From</th>
          </tr>
        </thead>
        <tbody>
          {columns.map((c, i) => (
            <tr key={`${c.column}-${i}`}>
              <td>{c.column}</td>
              <td>
                <span className={`class-pill class-pill--${c.change}`}>{c.change}</span>
              </td>
              <td>{c.from ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RowDiffsTable({ diffs }) {
  if (!diffs?.length) return null;
  return (
    <div className="surface-elevated mapping-editor__table-wrap">
      <table className="table-elevated mapping-editor__table">
        <thead>
          <tr>
            <th>Row</th>
            <th>Column</th>
            <th>Before</th>
            <th>After</th>
          </tr>
        </thead>
        <tbody>
          {diffs.flatMap((d) =>
            d.changes.map((c, i) => (
              <tr key={`${d.row_index}-${c.column}-${i}`}>
                <td>{d.row_index}</td>
                <td>{c.column}</td>
                <td className="run-meta__mono">{c.before ?? "—"}</td>
                <td className="run-meta__mono">{c.after ?? "—"}</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </div>
  );
}

function TransformedDataTable({ rows, truncated }) {
  if (!rows?.length) return null;
  const columns = Object.keys(rows[0]);
  return (
    <>
      <div className="surface-elevated mapping-editor__table-wrap">
        <table className="table-elevated mapping-editor__table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c}>{row[c] === null || row[c] === undefined ? "—" : String(row[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {truncated && (
        <p className="wizard-field__help">
          Showing the first {rows.length} rows. Download the full preview to see everything.
        </p>
      )}
    </>
  );
}

function TransformationPreviewPanel() {
  const { state, dispatch } = useWizard();
  const { source, target, transformationSpec } = state;
  const {
    mappingSheet,
    parsedMappingSheet,
    transformationRules,
    matchingRules,
    filterRules,
    mapping,
    generatedScript,
    scriptPreview,
    scriptApproval,
  } = transformationSpec;

  const [generateLoading, setGenerateLoading] = useState(false);
  const [generateError, setGenerateError] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [decisionError, setDecisionError] = useState(null);

  const script = generatedScript?.script;
  const hasMappingSheet = Boolean(mappingSheet?.name);
  const canGenerate =
    Boolean(source.dataset && target.dataset) &&
    (Boolean(parsedMappingSheet?.rows?.length) || Boolean(mapping?.display?.length));

  const generate = async () => {
    const mappingSheetPayload = buildMappingSheetPayload(parsedMappingSheet, mapping);
    if (!hasMappingPayload(mappingSheetPayload)) {
      setGenerateError("Upload a mapping sheet or confirm at least one field mapping first.");
      return;
    }
    setGenerateLoading(true);
    setGenerateError(null);
    try {
      const res = await api.post("/api/recon/transformations/generate", {
        mapping_sheet: mappingSheetPayload,
        rules: "",
        transformation_rules: cleanBusinessRules(transformationRules),
        matching_rules: cleanBusinessRules(matchingRules),
        filter_rules: cleanBusinessRules(filterRules),
        source_schema: source.dataset?.columns ?? [],
        target_schema: target.dataset?.columns ?? [],
        actor: "wizard-user",
      });
      dispatch({ type: WizardActions.SET_GENERATED_SCRIPT, generatedScript: res.data });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setGenerateError(typeof detail === "string" ? detail : "Transformation generation failed.");
    } finally {
      setGenerateLoading(false);
    }
  };

  const runPreview = async () => {
    if (!script) return;
    const rows = sampleRows(source, 200);
    if (!rows.length) {
      setPreviewError("Source data is no longer available. Go back and re-fetch or re-upload it.");
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const res = await api.post("/api/recon/transformations/preview", {
        script_id: script.script_id,
        rows,
        actor: "wizard-user",
      });
      dispatch({ type: WizardActions.SET_SCRIPT_PREVIEW, scriptPreview: res.data });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setPreviewError(typeof detail === "string" ? detail : "Preview execution failed.");
    } finally {
      setPreviewLoading(false);
    }
  };

  const approve = async () => {
    if (!scriptPreview) return;
    setDecisionLoading(true);
    setDecisionError(null);
    try {
      const res = await api.post("/api/recon/transformations/approve", {
        preview_id: scriptPreview.preview_id,
        approved_by: "wizard-user",
      });
      dispatch({ type: WizardActions.SET_SCRIPT_APPROVAL, scriptApproval: res.data?.approval });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setDecisionError(typeof detail === "string" ? detail : "Approval failed.");
    } finally {
      setDecisionLoading(false);
    }
  };

  const reject = async () => {
    if (!scriptPreview) return;
    setDecisionLoading(true);
    setDecisionError(null);
    try {
      await api.post("/api/recon/transformations/reject", {
        preview_id: scriptPreview.preview_id,
        actor: "wizard-user",
      });
      // Keep the preview visible (marked rejected) rather than clearing it —
      // "Re-run Preview" generates a fresh one when the user is ready to retry.
      dispatch({
        type: WizardActions.SET_SCRIPT_PREVIEW,
        scriptPreview: { ...scriptPreview, status: "rejected" },
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setDecisionError(typeof detail === "string" ? detail : "Rejection failed.");
    } finally {
      setDecisionLoading(false);
    }
  };

  const downloadPreview = () => {
    if (!scriptPreview) return;
    window.open(
      `${api.defaults.baseURL}/api/recon/transformations/preview/${scriptPreview.preview_id}/download`,
      "_blank",
    );
  };

  return (
    <section className="wizard-section">
      <h3 className="wizard-section__title">Transformation Preview</h3>
      <p className="wizard-field__help">
        The mapping sheet and rules are used to generate a transformation script. You review and
        approve the <strong>transformed data</strong> it produces — the script itself is an
        internal artifact and is never shown or approved directly.
      </p>

      <div className="contract-checklist">
        <StatusBadge
          ok={hasMappingSheet ? Boolean(parsedMappingSheet) : null}
          label={
            hasMappingSheet
              ? `Mapping Sheet ${parsedMappingSheet ? "Parsed" : "Uploaded"}`
              : "Mapping Sheet (optional — field mapping used instead)"
          }
        />
        <StatusBadge ok={script ? true : null} label="Transformation Generated" />
        <StatusBadge ok={scriptPreview ? true : null} label="Preview Executed" />
        <StatusBadge
          ok={scriptApproval ? true : scriptPreview?.status === "rejected" ? false : null}
          label={
            scriptApproval ? "Approved" : scriptPreview?.status === "rejected" ? "Rejected" : "Approved"
          }
        />
      </div>

      <div className="contract-actions">
        <button
          type="button"
          className="wizard-btn wizard-btn--primary"
          onClick={generate}
          disabled={!canGenerate || generateLoading}
        >
          {generateLoading ? "Generating…" : script ? "Regenerate Transformation" : "Generate Transformation"}
        </button>
        <button
          type="button"
          className="wizard-btn wizard-btn--primary"
          onClick={runPreview}
          disabled={!script || previewLoading}
        >
          {previewLoading ? "Running Preview…" : scriptPreview ? "Re-run Preview" : "Preview Transformation"}
        </button>
      </div>

      {generateError && <p className="wizard-step__error">⚠️ {generateError}</p>}
      {previewError && <p className="wizard-step__error">⚠️ {previewError}</p>}
      {decisionError && <p className="wizard-step__error">⚠️ {decisionError}</p>}

      {/* LLM provider failover succeeded (Groq→OpenAI) — non-blocking notice. */}
      {generatedScript?.fallback && generatedScript?.provider_notice && (
        <p className="wizard-step__hint">ℹ️ {generatedScript.provider_notice}</p>
      )}

      {generatedScript?.degraded && (
        <p className="wizard-step__hint">
          ⚠️ AI generation unavailable — used the deterministic fallback instead
          {generatedScript.degraded_reason ? `: ${generatedScript.degraded_reason}` : "."} The
          workflow continues normally; review the preview carefully.
        </p>
      )}

      {script && (
        <div className="contract-summary">
          <span className="contract-summary__chip">Generated By: {script.generated_by}</span>
          <ConfidenceBadge confidence={script.confidence} />
        </div>
      )}

      {script?.explanation?.length > 0 && (
        <div className="contract-json-wrap">
          <p className="wizard-field__help">Explanation</p>
          <ol className="wizard-step__list">
            {script.explanation.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </div>
      )}

      {scriptPreview && (
        <>
          <div className="contract-summary">
            <span className="contract-summary__chip">{scriptPreview.summary?.text}</span>
            <span className="contract-summary__chip">
              Total Rows Previewed: {scriptPreview.summary?.total_rows ?? 0}
            </span>
          </div>

          <p className="wizard-field__help">Modified Columns</p>
          <ModifiedColumnsTable columns={scriptPreview.modified_columns} />

          {scriptPreview.row_diffs?.length > 0 && (
            <>
              <p className="wizard-field__help">Row-Level Diffs (before → after)</p>
              <RowDiffsTable diffs={scriptPreview.row_diffs} />
            </>
          )}

          <div className="contract-actions">
            <button type="button" className="wizard-btn wizard-btn--ghost" onClick={downloadPreview}>
              Download Transformed Preview (CSV)
            </button>
            <button
              type="button"
              className="wizard-btn wizard-btn--primary"
              onClick={approve}
              disabled={Boolean(scriptApproval) || scriptPreview.status === "rejected" || decisionLoading}
            >
              {decisionLoading && !scriptApproval
                ? "Approving…"
                : scriptApproval
                  ? "Approved"
                  : "Approve Transformed Data"}
            </button>
            <button
              type="button"
              className="wizard-btn wizard-btn--ghost"
              onClick={reject}
              disabled={Boolean(scriptApproval) || scriptPreview.status === "rejected" || decisionLoading}
            >
              {scriptPreview.status === "rejected" ? "Rejected" : "Reject"}
            </button>
          </div>

          <p className="wizard-field__help">Full Transformed Dataset (preview)</p>
          <TransformedDataTable
            rows={scriptPreview.transformed_rows}
            truncated={scriptPreview.transformed_rows_truncated}
          />
        </>
      )}

      {!script && (
        <p className="wizard-field__help">
          Generate a transformation to preview the data it produces before approving it.
        </p>
      )}
    </section>
  );
}

export default TransformationPreviewPanel;
