import { useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import { appendDatasetSide, cleanBusinessRules } from "../lib/payload";
import {
  createBothSnapshots,
  createSnapshot,
  identicalDatasetReason,
  runContractReconciliation,
} from "../lib/reconRun";
import StepShell from "../components/StepShell";
import ContractRunResults from "../components/ContractRunResults";
import SummaryCards from "../../components/SummaryCards";
import ReconciliationResults from "../../components/ReconciliationResults";
import { Button, Alert } from "@bristlecone/canopy";

// Derives business_key / compare_fields for the script-flow production run
// from the same (possibly hand-edited) field mapping the contract flow uses.
// The script may have renamed source columns to their target names in the
// Shadow_Source; the backend resolves whichever name actually exists there.
function keysFromMapping(mapping) {
  const display = mapping?.display ?? [];
  const business_key = [];
  const compare_fields = [];
  for (const row of display) {
    if (!row.source_col || !row.target_col) continue;
    const pair = { source_field: row.source_col, target_field: row.target_col };
    if (/key/i.test(String(row.role))) business_key.push(pair);
    else compare_fields.push(pair);
  }
  return { business_key, compare_fields };
}

function ReconciliationRunStep() {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();
  const { source, target, comparisonType, transformationSpec, reconciliation } = state;
  // The Mapping step always approves its field mapping + transformation steps
  // there before Continue advances here — so this is the only contract Results
  // ever needs (no more separate Deterministic auto-compile path).
  const approvedContract = transformationSpec.contract;
  const scriptApproval = transformationSpec.scriptApproval;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [phase, setPhase] = useState(null); // "snapshots" | "run" | null

  // Contract runtime path: immutable snapshots -> deterministic engine
  // (Raw_Source + approved contract -> Shadow_Source vs Raw_Target). No
  // shadow-fingerprint pinning — the merged Mapping step's Mapping Review is
  // the review surface now, not a separate shadow-diff approval on this step.
  const runContractReconciliationStep = async (contract = approvedContract) => {
    let srcId = transformationSpec.sourceSnapshotId;
    let tgtId = transformationSpec.targetSnapshotId;
    if (!srcId || !tgtId) {
      setPhase("snapshots");
      const { sourceSnapshot, targetSnapshot } = await createBothSnapshots(
        source,
        target,
        comparisonType,
      );
      srcId = sourceSnapshot.snapshot_id;
      tgtId = targetSnapshot.snapshot_id;
    }

    setPhase("run");
    const result = await runContractReconciliation({
      contract,
      sourceSnapshotId: srcId,
      targetSnapshotId: tgtId,
      expectedShadowFingerprint: null,
      anchorDate: transformationSpec.anchorDate,
    });

    dispatch({
      type: WizardActions.SET_RECONCILIATION_RESULT,
      result: {
        ...result,
        source_snapshot: result.source_snapshot ?? { snapshot_id: srcId },
        target_snapshot: result.target_snapshot ?? { snapshot_id: tgtId },
      },
    });
    dispatch({ type: WizardActions.COMPLETE_STEP, step: "reconciliation" });
  };

  // Script runtime path (Transformation Preview → Approval): immutable
  // snapshots -> hash-pinned approved script -> Shadow_Source -> the same
  // unchanged deterministic reconciler. Only the source-transformation stage
  // differs from the contract path.
  const runScriptReconciliation = async () => {
    const { business_key, compare_fields } = keysFromMapping(transformationSpec.mapping);
    if (!business_key.length) {
      throw new Error(
        "Confirm at least one key field in Field Mapping before running reconciliation.",
      );
    }

    setPhase("snapshots");
    const [sourceSnapshot, targetSnapshot] = await Promise.all([
      createSnapshot("source", source, "Raw_Source", comparisonType),
      createSnapshot("target", target, "Raw_Target", comparisonType),
    ]);

    setPhase("run");
    const runRes = await api.post("/api/recon/transformations/run", {
      approval_id: scriptApproval.approval_id,
      source_snapshot_id: sourceSnapshot.snapshot_id,
      target_snapshot_id: targetSnapshot.snapshot_id,
      business_key,
      compare_fields,
      comparison_type: comparisonType?.id ?? "custom",
      source_type: source.kind ?? "excel",
      target_type: target.kind ?? "excel",
      actor: "wizard-user",
    });

    let detail = null;
    try {
      const detailRes = await api.get(`/api/recon/results/${runRes.data.result_id}?preview=500`);
      detail = detailRes.data;
    } catch {
      // Metadata + summary still render without the detail preview.
    }

    dispatch({
      type: WizardActions.SET_RECONCILIATION_RESULT,
      result: {
        engine: "script",
        ...runRes.data,
        source_snapshot: runRes.data.source_snapshot ?? sourceSnapshot,
        target_snapshot: runRes.data.target_snapshot ?? targetSnapshot,
        detail,
      },
    });
    dispatch({ type: WizardActions.COMPLETE_STEP, step: "reconciliation" });
  };

  const runReconciliation = async () => {
    setLoading(true);
    setError(null);

    try {
      // Debug trace: confirm the two sides are the datasets we expect.
      console.debug(
        `[wizard] RECONCILE | source="${source.dataset?.filename}" (${source.dataset?.rowCount} rows) ` +
          `vs target="${target.dataset?.filename}" (${target.dataset?.rowCount} rows)`,
      );

      const identical = identicalDatasetReason(source, target);
      if (identical) {
        throw new Error(
          `Source and target must be different datasets — ${identical}. ` +
            "Re-upload the correct file for one side before reconciling.",
        );
      }

      // With an approved contract or an approved transformation preview,
      // reconciliation runs through the matching runtime (never Raw_Source vs
      // Raw_Target directly). The legacy /reconcile path below only applies
      // when neither exists.
      if (approvedContract) {
        await runContractReconciliationStep();
        return;
      }
      if (scriptApproval) {
        await runScriptReconciliation();
        return;
      }

      const formData = new FormData();
      const okSource = appendDatasetSide(formData, "source", source);
      const okTarget = appendDatasetSide(formData, "target", target);
      if (!okSource || !okTarget) {
        throw new Error(
          "Source or target data is no longer available. Go back to Steps 1–2 and re-fetch or re-upload it.",
        );
      }

      if (transformationSpec.mapping?.mapping) {
        formData.append("mapping_json", JSON.stringify(transformationSpec.mapping.mapping));
      }

      // Carry business context + structured rules + mapping-sheet metadata
      // alongside the reconciliation. /reconcile ignores fields it doesn't use.
      formData.append("comparison_type", comparisonType?.id ?? "");
      formData.append(
        "rules_text",
        JSON.stringify({
          transformation_rules: cleanBusinessRules(transformationSpec.transformationRules),
          matching_rules: cleanBusinessRules(transformationSpec.matchingRules),
          filter_rules: cleanBusinessRules(transformationSpec.filterRules),
        }),
      );
      if (transformationSpec.mappingSheet?.name) {
        formData.append("mapping_sheet_name", transformationSpec.mappingSheet.name);
      }

      // Date Alignment UI was removed; filter to the overlap window when one
      // exists and otherwise proceed on the full data instead of hard-erroring.
      formData.append("date_scope", "overlap");
      formData.append("override_no_overlap", "true");

      const res = await api.post("/reconcile", formData);
      dispatch({ type: WizardActions.SET_RECONCILIATION_RESULT, result: res.data });
      dispatch({ type: WizardActions.COMPLETE_STEP, step: "reconciliation" });
    } catch (err) {
      if (err?.response?.status === 409) {
        // The reviewed shadow is stale (contract/source changed since review).
        setError(
          "The shadow dataset no longer matches what was approved in Review Changes. " +
            "Go back to Review Changes and re-approve the shadow before running.",
        );
      } else {
        const detail = err?.response?.data?.detail;
        const message =
          typeof detail === "string"
            ? detail
            : detail?.message || err?.message || "Reconciliation failed.";
        setError(message);
      }
    } finally {
      setLoading(false);
      setPhase(null);
    }
  };

  // Manual correction path. Editing hands this run to the human: the prior
  // approval is dropped (auto or manual — CLAIM_FOR_HUMAN does not care which),
  // the authored steps are kept as the working draft, and re-approval back on
  // the Mapping step is an explicit click even if the edited chain would pass
  // every auto-approve condition. A human touched it, so it stays human-owned
  // for this run.
  const editTransformationRules = () => {
    dispatch({ type: WizardActions.CLAIM_FOR_HUMAN });
    navigate("/reconciliation/transformation-spec");
  };

  const loadingLabel =
    phase === "snapshots"
      ? "Creating snapshots…"
      : phase === "run"
        ? "Executing transformation…"
        : "Reconciling…";
  const isContractResult = reconciliation?.engine === "contract" || reconciliation?.engine === "script";

  return (
    <StepShell stepKey="reconciliation" canContinue>
      <div className="recon-run">
        <Button
          type="button"
          variant="primary"
          size="lg"
          onClick={runReconciliation}
          loading={loading}
          disabled={loading}
        >
          {loading ? loadingLabel : reconciliation ? "Re-run Reconciliation" : "Run Reconciliation"}
        </Button>
        {approvedContract && (
          <Button type="button" variant="secondary" size="lg" onClick={editTransformationRules} disabled={loading}>
            Edit transformation rules
          </Button>
        )}
        <span className="recon-run__hint">
          {source.dataset?.filename} → {target.dataset?.filename}
          {comparisonType ? ` · ${comparisonType.label}` : ""}
          {approvedContract
            ? ` · Transformation Rules ${approvedContract.contract_id} v${approvedContract.contract_version}` +
              (transformationSpec.approvalMode === "auto"
                ? " · approved automatically (all checks passed)"
                : transformationSpec.approvalMode === "manual"
                  ? " · approved by you"
                  : "")
            : scriptApproval
              ? ` · Approved transformation (${scriptApproval.approval_id})`
              : " · no transformation rules (direct comparison)"}
          {reconciliation?.anchor_date
            ? ` · Anchor ${reconciliation.anchor_date} (${
                reconciliation.anchor_resolver === "inferred_from_target"
                  ? "inferred from target"
                  : reconciliation.anchor_resolver === "explicit"
                    ? "set by you"
                    : "today"
              })`
            : ""}
        </span>
      </div>

      {error && (
        <Alert variant="error" style={{ marginTop: 12 }}>{error}</Alert>
      )}

      {isContractResult ? (
        <div className="recon-run__section">
          <ContractRunResults result={reconciliation} />
        </div>
      ) : (
        <>
          {reconciliation?.summary && (
            <div className="recon-run__section">
              <SummaryCards summary={reconciliation.summary} />
            </div>
          )}

          {reconciliation && (
            <div className="recon-run__section">
              <ReconciliationResults reconResult={reconciliation} />
            </div>
          )}
        </>
      )}
    </StepShell>
  );
}

export default ReconciliationRunStep;
