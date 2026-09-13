// Shared contract-engine runtime helpers used by both the Review Changes
// checkpoint and the Reconciliation step: snapshot ingestion, the guarded run,
// and the identical-dataset guard. Keeping these in one place ensures the
// shadow the user reviews is produced from the same snapshots the run reuses.
import api from "../../services/api";

// Guards against accidentally reconciling a dataset against itself — the
// symptom of source/target state not being isolated. Returns a reason string
// when the two sides resolve to the same dataset, otherwise null.
export function identicalDatasetReason(source, target) {
  const s = source?.dataset;
  const t = target?.dataset;
  if (!s || !t) return null;

  if (s.datasetId && s.datasetId === t.datasetId) {
    return "source and target point to the same dataset id";
  }

  const sameColumns =
    Array.isArray(s.columns) &&
    Array.isArray(t.columns) &&
    s.columns.length === t.columns.length &&
    s.columns.every((c, i) => c === t.columns[i]);

  if (
    s.filename &&
    s.filename === t.filename &&
    s.rowCount === t.rowCount &&
    s.colCount === t.colCount &&
    sameColumns
  ) {
    return `source and target are the same file ("${s.filename}", ${s.rowCount} rows)`;
  }
  return null;
}

// Snapshot one wizard side into the immutable raw layer. Excel datasets travel
// as the original file; SAP-fetched datasets travel as their in-memory rows.
export async function createSnapshot(role, roleState, layer, comparisonType) {
  const dataset = roleState?.dataset;
  const formData = new FormData();
  formData.append("layer", layer);
  formData.append("source_type", roleState?.kind ?? "excel");
  if (comparisonType?.id) formData.append("comparison_type", comparisonType.id);
  formData.append("created_by", "wizard-user");

  if (roleState?.kind === "excel" && dataset?.file) {
    formData.append("file", dataset.file);
    if (dataset.sheet) formData.append("sheet_name", dataset.sheet);
  } else if (Array.isArray(dataset?.rows) && dataset.rows.length > 0) {
    formData.append("rows", JSON.stringify(dataset.rows));
  } else {
    throw new Error(
      `The ${role} data is no longer available. Go back to Steps 1–2 and re-fetch or re-upload it.`,
    );
  }

  const res = await api.post("/api/recon/snapshots/upload", formData);
  return res.data?.snapshot;
}

// Create both raw snapshots for a contract run in parallel.
export async function createBothSnapshots(source, target, comparisonType) {
  const [sourceSnapshot, targetSnapshot] = await Promise.all([
    createSnapshot("source", source, "Raw_Source", comparisonType),
    createSnapshot("target", target, "Raw_Target", comparisonType),
  ]);
  return { sourceSnapshot, targetSnapshot };
}

// Load a result's detail preview; tolerant of failure (summary still renders).
async function fetchResultDetail(resultId) {
  try {
    const res = await api.get(`/api/recon/results/${resultId}?preview=500`);
    return res.data;
  } catch {
    return null;
  }
}

// Execute an approved contract against pre-created snapshots. When
// expectedShadowFingerprint is supplied the backend verifies the rebuilt
// Shadow_Source matches what was reviewed (409 otherwise). `anchorDate`
// ("YYYY-MM-DD" | null/undefined) should be the SAME value (if any) the
// preview that produced expectedShadowFingerprint was built with — omitting
// it here lets the backend re-resolve its own anchor (explicit override,
// then target-inferred, then wall-clock; see service._resolve_run_anchor),
// which reproduces the previewed shadow exactly as long as the target data
// hasn't changed since, but passing the user's own explicit override through
// keeps that guarantee even when one was set. Returns the shape the wizard
// stores under `reconciliation`.
export async function runContractReconciliation({
  contract,
  sourceSnapshotId,
  targetSnapshotId,
  expectedShadowFingerprint = null,
  anchorDate = null,
}) {
  const runRes = await api.post("/api/recon/runs", {
    contract_id: contract.contract_id,
    contract_version: contract.contract_version,
    source_snapshot_id: sourceSnapshotId,
    target_snapshot_id: targetSnapshotId,
    expected_shadow_fingerprint: expectedShadowFingerprint,
    anchor_date: anchorDate || null,
    actor: "wizard-user",
  });

  const detail = await fetchResultDetail(runRes.data.result_id);
  return {
    engine: "contract",
    ...runRes.data,
    detail,
  };
}

// Deep-link to the downloadable 2-sheet (Summary + All Records) workbook for a run.
export function getComparisonUrl(runId) {
  return `${api.defaults.baseURL}/api/recon/runs/${runId}/comparison.xlsx`;
}
