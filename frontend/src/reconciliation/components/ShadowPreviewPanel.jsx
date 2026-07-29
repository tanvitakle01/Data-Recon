// Inline shadow preview + approval, embedded in the Mapping step's Manual
// flow (previously the standalone "Review Changes" step). It builds the
// Shadow_Source from the approved contract + source snapshot, shows a
// before/after comparison, the applied operations, and a target preview, and
// requires the user to APPROVE the shadow (pinning its fingerprint) before the
// run is allowed. Once approved, an inline "Run Reconciliation" runs against
// the approved contract (verifying the fingerprint) and navigates to Results.
//
// Shadow approval is REQUIRED — this only relocates the gate onto the Mapping
// page; it does not weaken it. The run still passes expected_shadow_fingerprint
// so the backend 409s if the contract/source drifted since approval.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import {
  createBothSnapshots,
  generateInsightsForRun,
  identicalDatasetReason,
  runContractReconciliation,
} from "../lib/reconRun";
import BeforeAfterCurtain from "./BeforeAfterCurtain";
import { Button, Badge, Alert, Skeleton } from "@bristlecone/canopy";

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
        <Button type="button" variant="outline" disabled={clamped <= 0}
          onClick={() => setPage(clamped - 1)}>◀ Prev</Button>
        <span className="review-pager__label">Page {clamped + 1} of {pages}</span>
        <Button type="button" variant="outline" disabled={clamped >= pages - 1}
          onClick={() => setPage(clamped + 1)}>Next ▶</Button>
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
              <td><Badge variant="warning">{op.op}</Badge></td>
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

// Renders nothing until a Manual contract is approved (the parent gates on
// that too). `contract` is the approved Manual TransformationContract.
function ShadowPreviewPanel() {
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
          // A reused snapshot id can be stale (store cleared / server
          // restarted / resumed draft) — the backend reports 404/400. Recreate
          // the snapshots and retry ONCE so the panel self-heals.
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
    dispatch({
      type: WizardActions.SET_SHADOW_APPROVAL,
      shadowApproved: shadowPreview.shadow_fingerprint,
    });
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
      dispatch({ type: WizardActions.COMPLETE_STEP, step: "transformationSpec" });
      dispatch({ type: WizardActions.COMPLETE_STEP, step: "reconciliation" });
      dispatch({ type: WizardActions.GO_TO_STEP, step: "reconciliation" });
      generateInsightsForRun(result.run_id);
      navigate("/reconciliation/reconciliation");
    } catch (err) {
      if (err?.response?.status === 409) {
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

  if (!contract) return null;

  const loadingLabel = phase === "snapshots" ? "Creating snapshots…" : "Generating shadow dataset…";

  return (
    <section className="wizard-section">
      <h3 className="wizard-section__title">Transformation Preview</h3>
      <p className="wizard-field__help">
        Inspect the transformed shadow source against the original and the target, then approve it
        before reconciliation runs against it. Approval is required.
      </p>

      <div className="review-meta">
        <Badge variant="default">
          Transformation Rules: {contract.contract_id} v{contract.contract_version}
        </Badge>
        {shadowPreview && (
          <>
            <Badge variant="default">
              Source rows: {shadowPreview.source?.total_rows ?? 0}
            </Badge>
            <Badge variant="default">
              Shadow rows: {shadowPreview.shadow?.total_rows ?? 0}
              {shadowPreview.row_count_changed ? " (changed by filters/aggregation)" : ""}
            </Badge>
            {shadowPreview.target && (
              <Badge variant="default">
                Target rows: {shadowPreview.target?.total_rows ?? 0}
              </Badge>
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

      {error && <Alert variant="error" style={{ marginTop: 8 }}>{error}</Alert>}
      {loading && (
        <div style={{ display: "grid", gap: 8, marginTop: 8 }} aria-label={loadingLabel}>
          <Skeleton style={{ height: 120 }} />
          <Skeleton style={{ height: 32, width: "40%" }} />
        </div>
      )}

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
                  <Badge key={i} variant="default">
                    {a.source_field}: {a.aggregation}
                  </Badge>
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
            <Button
              type="button"
              variant="outline"
              onClick={() => buildPreview({ force: true })}
              disabled={loading || running}
            >
              Regenerate Shadow
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={approveShadow}
              disabled={Boolean(shadowApproved) || running}
            >
              {shadowApproved ? "✓ Shadow Approved" : "Approve Shadow Dataset"}
            </Button>
          </div>

          {shadowApproved && (
            <>
              <Alert variant="success" style={{ marginTop: 8 }}>
                Mapping done, shadow approved (fingerprint {String(shadowApproved).slice(0, 12)}…).
                You can now run reconciliation.
              </Alert>
              <div className="contract-actions">
                <Button
                  type="button"
                  variant="primary"
                  size="lg"
                  onClick={runReconciliation}
                  loading={running}
                  disabled={running}
                >
                  {running ? "Reconciling…" : "Run Reconciliation"}
                </Button>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}

export default ShadowPreviewPanel;
