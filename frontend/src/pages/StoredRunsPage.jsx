import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, ConfirmDialog, Modal } from "@bristlecone/canopy";
import { FiDownload, FiEye, FiPlay, FiRefreshCw, FiTrash2 } from "react-icons/fi";
import {
  deleteStoredRun,
  exportPartialResults,
  getPartialResults,
  listStoredRuns,
  resumeRun,
} from "../services/storedRunsApi";

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function StoredRunsPage() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const [pendingDelete, setPendingDelete] = useState(null);
  const [staleResume, setStaleResume] = useState(null); // { graphRunId, message }
  const [viewing, setViewing] = useState(null); // { run, result, previewRows }
  const [resumedNotice, setResumedNotice] = useState(null); // graph_run_id of a just-resumed run

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRuns(await listStoredRuns());
    } catch {
      setError("Failed to load stored runs.");
    } finally {
      setLoading(false);
    }
  }, []);

  const didInit = useRef(false);
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    load();
  }, [load]);

  const doResume = async (graphRunId, { force = false } = {}) => {
    setBusyId(graphRunId);
    setError(null);
    try {
      await resumeRun(graphRunId, { force });
      setStaleResume(null);
      setResumedNotice(graphRunId);
      await load();
    } catch (err) {
      if (err.response?.status === 409 && err.response?.data?.detail?.includes("changed since")) {
        setStaleResume({ graphRunId, message: err.response.data.detail });
      } else {
        setError("Resume failed.");
      }
    } finally {
      setBusyId(null);
    }
  };

  const view = async (run) => {
    setBusyId(run.graph_run_id);
    setError(null);
    try {
      const data = await getPartialResults(run.graph_run_id);
      setViewing({ run, ...data });
    } catch {
      setError("No partial results are available for this run yet.");
    } finally {
      setBusyId(null);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setBusyId(pendingDelete.graph_run_id);
    try {
      await deleteStoredRun(pendingDelete.graph_run_id);
      setPendingDelete(null);
      await load();
    } catch {
      setError("Delete failed.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <div className="ct-card__head" style={{ padding: 0, marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontWeight: 900, letterSpacing: "-0.02em" }}>Stored Runs</h1>
          <p style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
            Reconciliation runs suspended mid-flight — resume from exactly the batch they stopped
            at, or view/export what they'd already completed.
          </p>
        </div>
        <span className="ct-card__spacer" />
        <Button type="button" variant="outline" size="sm" onClick={load} disabled={loading}>
          <FiRefreshCw /> Refresh
        </Button>
      </div>

      {resumedNotice && (
        <Alert variant="success">
          Run {resumedNotice} is resuming in the background from where it left off — its progress
          isn't tracked on this page; check back here or in the reconciliation history once it
          completes.
        </Alert>
      )}
      {error && <Alert variant="error">{error}</Alert>}
      {loading && !runs.length && <p>Loading…</p>}
      {!loading && !runs.length && (
        <p style={{ color: "#64748b" }}>
          Nothing here yet. Suspend an in-progress reconciliation run to park it for later.
        </p>
      )}

      {runs.length > 0 && (
        <div className="ct-table-wrap">
          <table className="ct-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Suspended</th>
                <th>Reason</th>
                <th>Progress</th>
                <th>Expires</th>
                <th aria-label="Row actions" />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.graph_run_id}>
                  <td>
                    <div>{run.name || run.graph_run_id}</div>
                    <code style={{ fontSize: 12, color: "#94a3b8" }}>{run.graph_run_id}</code>
                  </td>
                  <td>{formatDate(run.suspended_at)}</td>
                  <td>{run.suspend_reason || "—"}</td>
                  <td>
                    {run.batches_total
                      ? `Batch ${run.batches_completed} of ${run.batches_total}`
                      : `${run.batches_completed} batch(es) completed`}
                  </td>
                  <td>{formatDate(run.expires_at)}</td>
                  <td style={{ display: "flex", gap: 4 }}>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-8 text-xs"
                      onClick={() => doResume(run.graph_run_id)}
                      disabled={busyId === run.graph_run_id}
                      aria-label="Resume run"
                    >
                      <FiPlay /> Resume
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-8 text-xs"
                      onClick={() => view(run)}
                      disabled={busyId === run.graph_run_id}
                      aria-label="View partial results"
                    >
                      <FiEye />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-8 text-xs"
                      onClick={() => exportPartialResults(run.graph_run_id)}
                      aria-label="Export partial results"
                    >
                      <FiDownload />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-8 text-xs"
                      onClick={() => setPendingDelete(run)}
                      disabled={busyId === run.graph_run_id}
                      aria-label="Delete stored run"
                    >
                      <FiTrash2 />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={Boolean(viewing)}
        onClose={() => setViewing(null)}
        title={`Partial results — ${viewing?.run?.name || viewing?.run?.graph_run_id || ""}`}
      >
        {viewing && (
          <div>
            <p className="wizard-field__help" style={{ marginTop: 0 }}>
              {viewing.result?.summary?.match ?? 0} matched / {viewing.result?.summary?.total ?? 0} total
              rows across the batches completed so far (first 200 rows shown).
            </p>
            {viewing.preview_rows?.length > 0 ? (
              <div className="ct-table-wrap">
                <table className="ct-table">
                  <thead>
                    <tr>
                      {Object.keys(viewing.preview_rows[0]).map((col) => (
                        <th key={col}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {viewing.preview_rows.map((row, i) => (
                      <tr key={i}>
                        {Object.keys(viewing.preview_rows[0]).map((col) => (
                          <td key={col}>{String(row[col] ?? "")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p>No rows recorded yet.</p>
            )}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        title="Delete stored run"
        message={`Discard "${pendingDelete?.name || pendingDelete?.graph_run_id}"? Its checkpoint and partial results are permanently removed. This cannot be undone.`}
        confirmText="Delete"
        variant="destructive"
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />

      <ConfirmDialog
        isOpen={Boolean(staleResume)}
        title="Source or target data has changed"
        message={`${staleResume?.message || ""} Resuming anyway will mix two data vintages in one result.`}
        confirmText="Resume anyway"
        cancelText="Cancel"
        variant="destructive"
        onConfirm={() => doResume(staleResume.graphRunId, { force: true })}
        onCancel={() => setStaleResume(null)}
      />
    </div>
  );
}

export default StoredRunsPage;
