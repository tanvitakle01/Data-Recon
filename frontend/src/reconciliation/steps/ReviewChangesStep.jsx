// Review Changes — the mandatory contract-engine checkpoint between contract
// approval and reconciliation. It builds the Shadow_Source from the approved
// contract + source snapshot, shows a before/after comparison, the applied
// operations, and a target preview, and requires the user to APPROVE the shadow
// (pinning its fingerprint) before the run is allowed. Iteration is supported:
// go Back to edit rules/mapping and re-approve the contract, then return here —
// a fresh contract invalidates the review and rebuilds the shadow.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import {
  createBothSnapshots,
  identicalDatasetReason,
  runContractReconciliation,
} from "../lib/reconRun";
import BeforeAfterCurtain from "../components/BeforeAfterCurtain";

function dedupe(list) {
  return Array.from(new Set(list.filter(Boolean)));
}

function cellText(v) {
  return v === null || v === undefined || v === "" ? "—" : String(v);
}

// Simple client-side paginated, read-only table for the IBP target preview.
function PaginatedTable({ columns, rows, pageSize = 10 }) {
  const [page, setPage] = useState(0);
  if (!columns?.length || !rows?.length) {
    return <p className="wizard-field__help">No target rows to preview.</p>;
  }
  const pages = Math.ceil(rows.length / pageSize);
  const clamped = Math.min(page, pages - 1);
  const slice = rows.slice(clamped * pageSize, clamped * pageSize + pageSize);
  return (
    <>
      <div className="surface-elevated mapping-editor__table-wrap">
        <table className="table-elevated mapping-editor__table">
          <thead>
            <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {slice.map((row, i) => (
              <tr key={i}>{columns.map((c) => <td key={c}>{cellText(row[c])}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="review-pager">
        <button type="button" className="wizard-btn wizard-btn--ghost" disabled={clamped <= 0}
          onClick={() => setPage(clamped - 1)}>◀ Prev</button>
        <span className="review-pager__label">Page {clamped + 1} of {pages}</span>
        <button type="button" className="wizard-btn wizard-btn--ghost" disabled={clamped >= pages - 1}
          onClick={() => setPage(clamped + 1)}>Next ▶</button>
      </div>
    </>
  );
}

function OperationsTable({ operations }) {
  if (!operations?.length) {
    return <p className="wizard-field__help">These transformation rules apply no value operations.</p>;
  }
  return (
    <div className="surface-elevated mapping-editor__table-wrap">
      <table className="table-elevated mapping-editor__table">
        <thead>
          <tr><th>#</th><th>Operation</th><th>Field</th><th>Parameters</th></tr>
        </thead>
        <tbody>
          {operations.map((op, i) => (
            <tr key={i}>
              <td>{i + 1}</td>
              <td><span className="class-pill class-pill--modified">{op.op}</span></td>
              <td>{op.field ?? "—"}</td>
              <td className="run-meta__mono">
                {op.params && Object.keys(op.params).length ? JSON.stringify(op.params) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReviewChangesStep() {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();
  const { source, target, comparisonType, transformationSpec } = state;
  const { contract, sourceSnapshotId, targetSnapshotId, shadowPreview, shadowApproved } =
    transformationSpec;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [phase, setPhase] = useState(null);
  const [running, setRunning] = useState(false);
  // Prevents the build effect from firing twice for the same contract build.
  const buildKeyRef = useRef(null);

  const buildPreview = useCallback(
    async ({ force = false } = {}) => {
      if (!contract) return;
      setLoading(true);
      setError(null);

      // Create both raw snapshots and remember their ids on the wizard.
      const makeSnapshots = async () => {
        setPhase("snapshots");
        const { sourceSnapshot, targetSnapshot } = await createBothSnapshots(
          source,
          target,
          comparisonType,
        );
        dispatch({
          type: WizardActions.SET_SHADOW_SNAPSHOTS,
          sourceSnapshotId: sourceSnapshot.snapshot_id,
          targetSnapshotId: targetSnapshot.snapshot_id,
        });
        return { srcId: sourceSnapshot.snapshot_id, tgtId: targetSnapshot.snapshot_id };
      };

      const postPreview = async (srcId, tgtId) => {
        setPhase("shadow");
        const res = await api.post("/api/recon/shadow-preview", {
          contract_id: contract.contract_id,
          contract_version: contract.contract_version,
          source_snapshot_id: srcId,
          target_snapshot_id: tgtId,
          // Sample size is governed server-side by RECON_PREVIEW_ROWS so the
          // preview payload stays small for large SAP S/4 & IBP datasets; the
          // full transformed dataset is never shipped to the browser.
          actor: "wizard-user",
        });
        return res.data;
      };

      try {
        const identical = identicalDatasetReason(source, target);
        if (identical) {
          throw new Error(
            `Source and target must be different datasets — ${identical}. ` +
              "Re-upload the correct file for one side.",
          );
        }

        // Reuse remembered snapshots when we have them (and aren't forcing);
        // otherwise create fresh ones from the in-memory datasets.
        let reused = !force && Boolean(sourceSnapshotId && targetSnapshotId);
        let srcId = sourceSnapshotId;
        let tgtId = targetSnapshotId;
        if (!reused) {
          ({ srcId, tgtId } = await makeSnapshots());
        }

        try {
          const data = await postPreview(srcId, tgtId);
          dispatch({ type: WizardActions.SET_SHADOW_PREVIEW, shadowPreview: data });
        } catch (err) {
          // A reused snapshot id can be stale (store cleared, server restarted
          // with a different RECON_STORE_DIR, or a resumed draft). The backend
          // reports that as 404 "Unknown snapshot" (or 400) — recreate the
          // snapshots from the datasets we still hold and retry ONCE, so the
          // review page self-heals instead of dead-ending on a 404.
          const status = err?.response?.status;
          if (reused && (status === 404 || status === 400)) {
            ({ srcId, tgtId } = await makeSnapshots());
            const data = await postPreview(srcId, tgtId);
            dispatch({ type: WizardActions.SET_SHADOW_PREVIEW, shadowPreview: data });
          } else {
            throw err;
          }
        }
      } catch (err) {
        const detail = err?.response?.data?.detail;
        const msg = typeof detail === "string" ? detail : err?.message;
        // createBothSnapshots throws this when a hard refresh dropped the
        // in-memory file/rows — point the user at the fix rather than a 404.
        if (msg && msg.includes("no longer available")) {
          setError(
            "The uploaded source/target data was dropped (likely a page refresh). Go back to the " +
              "Source/Target steps and re-upload or re-fetch it, then return here.",
          );
        } else {
          setError(msg || "Failed to build the shadow dataset.");
        }
      } finally {
        setLoading(false);
        setPhase(null);
      }
    },
    [contract, source, target, comparisonType, sourceSnapshotId, targetSnapshotId, dispatch],
  );

  // Auto-build the shadow once per approved contract build when none exists yet.
  useEffect(() => {
    if (!contract) return;
    const key = `${contract.contract_id}:v${contract.contract_version}`;
    if (shadowPreview) {
      buildKeyRef.current = key;
      return;
    }
    if (buildKeyRef.current === key || loading) return;
    buildKeyRef.current = key;
    buildPreview();
  }, [contract, shadowPreview, loading, buildPreview]);

  const columns = useMemo(() => {
    if (!shadowPreview) return [];
    return dedupe([...(shadowPreview.source?.columns ?? []), ...(shadowPreview.shadow?.columns ?? [])]);
  }, [shadowPreview]);

  const approveShadow = () => {
    if (!shadowPreview) return;
    dispatch({ type: WizardActions.SET_SHADOW_APPROVAL, shadowApproved: shadowPreview.shadow_fingerprint });
    dispatch({ type: WizardActions.COMPLETE_STEP, step: "reviewChanges" });
  };

  const runReconciliation = async () => {
    if (!shadowApproved) return;
    setRunning(true);
    setError(null);
    try {
      const result = await runContractReconciliation({
        contract,
        sourceSnapshotId,
        targetSnapshotId,
        expectedShadowFingerprint: shadowApproved,
      });
      dispatch({
        type: WizardActions.SET_RECONCILIATION_RESULT,
        result: {
          ...result,
          source_snapshot: result.source_snapshot ?? { snapshot_id: sourceSnapshotId },
          target_snapshot: result.target_snapshot ?? { snapshot_id: targetSnapshotId },
        },
      });
      dispatch({ type: WizardActions.COMPLETE_STEP, step: "reviewChanges" });
      dispatch({ type: WizardActions.COMPLETE_STEP, step: "reconciliation" });
      dispatch({ type: WizardActions.GO_TO_STEP, step: "reconciliation" });
      navigate("/reconciliation/reconciliation");
    } catch (err) {
      if (err?.response?.status === 409) {
        // Stale shadow (contract/source changed) — drop the approval and rebuild.
        setError("The shadow dataset changed since you approved it. Rebuilding it for re-review.");
        dispatch({ type: WizardActions.SET_SHADOW_PREVIEW, shadowPreview: null });
        buildKeyRef.current = null;
      } else {
        const detail = err?.response?.data?.detail;
        setError(typeof detail === "string" ? detail : "Reconciliation failed.");
      }
    } finally {
      setRunning(false);
    }
  };

  const goBackToEdit = () => {
    dispatch({ type: WizardActions.GO_TO_STEP, step: "transformationSpec" });
    navigate("/reconciliation/transformation-spec");
  };

  // ── guard: this checkpoint needs an approved contract ─────────────────────
  if (!contract) {
    return (
      <section className="wizard-step">
        <header className="wizard-step__header">
          <p className="wizard-step__eyebrow">Step 5 of 6</p>
          <h2 className="wizard-step__title">Review Changes</h2>
          <p className="wizard-step__desc">Approve transformation rules first.</p>
        </header>
        <div className="wizard-step__body">
          <p className="wizard-field__help">
            No approved transformation rules yet. Go back to the Transformation Spec step, generate
            and approve transformation rules, then return here to review the shadow dataset they
            produce.
          </p>
        </div>
        <footer className="wizard-step__footer">
          <button type="button" className="wizard-btn wizard-btn--ghost" onClick={goBackToEdit}>
            Back
          </button>
        </footer>
      </section>
    );
  }

  const loadingLabel = phase === "snapshots" ? "Creating snapshots…" : "Generating shadow dataset…";
  const sourceFile = source.dataset?.filename ?? shadowPreview?.source?.snapshot?.lineage?.filename ?? "—";
  const targetFile = target.dataset?.filename ?? shadowPreview?.target?.snapshot?.lineage?.filename ?? "—";

  return (
    <section className="wizard-step">
      <header className="wizard-step__header">
        <p className="wizard-step__eyebrow">Step 5 of 6</p>
        <h2 className="wizard-step__title">Transformation Preview</h2>
        <p className="wizard-step__desc">
          Inspect the transformed shadow source against the original and the target, then approve it
          before reconciliation runs against it.
        </p>
      </header>

      <div className="wizard-step__body">
        <div className="review-meta">
          <span className="contract-summary__chip">Source: {sourceFile}</span>
          <span className="contract-summary__chip">Target: {targetFile}</span>
          <span className="contract-summary__chip">
            Transformation Rules: {contract.contract_id} v{contract.contract_version}
          </span>
          {shadowPreview && (
            <>
              <span className="contract-summary__chip">
                Source rows: {shadowPreview.source?.total_rows ?? 0}
              </span>
              <span className="contract-summary__chip">
                Shadow rows: {shadowPreview.shadow?.total_rows ?? 0}
                {shadowPreview.row_count_changed ? " (changed by filters/aggregation)" : ""}
              </span>
              {shadowPreview.target && (
                <span className="contract-summary__chip">
                  Target rows: {shadowPreview.target?.total_rows ?? 0}
                </span>
              )}
            </>
          )}
        </div>

        {!loading && shadowPreview && (
          <p className="wizard-field__help">
            Showing a sample of up to {shadowPreview.preview_rows ?? 0} rows per dataset. Approval is
            applied to the <strong>full</strong> transformed dataset, not just this sample.
          </p>
        )}

        {error && <p className="wizard-step__error">⚠️ {error}</p>}

        {loading && <p className="wizard-step__hint">{loadingLabel}</p>}

        {!loading && shadowPreview && (
          <>
            <section className="wizard-section">
              <h3 className="wizard-section__title">Source → Transformed (Shadow Source) Preview</h3>
              <BeforeAfterCurtain columns={columns} diffs={shadowPreview.diffs} />
            </section>

            <section className="wizard-section">
              <h3 className="wizard-section__title">Key Transformation Summary</h3>
              <OperationsTable operations={shadowPreview.operations} />
              {shadowPreview.aggregation_rules?.length > 0 && (
                <div className="review-meta" style={{ marginTop: 10 }}>
                  {shadowPreview.aggregation_rules.map((a, i) => (
                    <span key={i} className="contract-summary__chip">
                      {a.source_field}: {a.aggregation}
                    </span>
                  ))}
                </div>
              )}
            </section>

            <section className="wizard-section">
              <h3 className="wizard-section__title">Target Dataset Preview</h3>
              <PaginatedTable
                columns={shadowPreview.target?.columns ?? []}
                rows={shadowPreview.target?.rows ?? []}
              />
            </section>

            <div className="contract-actions">
              <button
                type="button"
                className="wizard-btn wizard-btn--ghost"
                onClick={() => buildPreview({ force: true })}
                disabled={loading || running}
              >
                Regenerate Shadow
              </button>
              <button
                type="button"
                className="wizard-btn wizard-btn--primary"
                onClick={approveShadow}
                disabled={Boolean(shadowApproved) || running}
              >
                {shadowApproved ? "✓ Shadow Approved" : "Approve Shadow Dataset"}
              </button>
            </div>
            {shadowApproved && (
              <p className="wizard-step__hint">
                Shadow approved (fingerprint {String(shadowApproved).slice(0, 12)}…). You can now run
                reconciliation.
              </p>
            )}
          </>
        )}
      </div>

      <footer className="wizard-step__footer">
        <button type="button" className="wizard-btn wizard-btn--ghost" onClick={goBackToEdit} disabled={running}>
          Back — Edit Rules & Mapping
        </button>
        <button
          type="button"
          className="wizard-btn wizard-btn--primary"
          onClick={runReconciliation}
          disabled={!shadowApproved || running}
        >
          {running ? "Reconciling…" : "Run Reconciliation"}
        </button>
      </footer>
    </section>
  );
}

export default ReviewChangesStep;
