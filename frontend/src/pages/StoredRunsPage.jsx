import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Badge, Button, ConfirmDialog, Modal } from "@bristlecone/canopy";
import { FiDownload, FiEye, FiPlay, FiRefreshCw, FiTrash2 } from "react-icons/fi";
import {
  deleteStoredRun,
  exportPartialResults,
  getPartialResults,
  listStoredRuns,
  resumeRun,
} from "../services/storedRunsApi";
import { getComparisonUrl } from "../reconciliation/lib/reconRun";
import { FieldDiffs } from "../reconciliation/components/reconRowDisplay";
import { ROW_CLASS } from "../reconciliation/components/reconRowClassification";
import ShortId from "../components/ShortId";

// Statuses a run can be in while it's still actively executing — mirrors
// backend/recon_engine/run_registry.py's ACTIVE_STATES. A run in one of these
// keeps polling for live progress; Resume is hidden and Delete is disabled.
const ACTIVE_STATUSES = new Set(["running", "waiting_for_input", "cancelling", "suspending", "stalled"]);

const STATUS_LABELS = {
  suspended: "Suspended",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  waiting_for_input: "Waiting for input",
  stalled: "Stalled",
  cancelling: "Cancelling",
  suspending: "Suspending",
};

const LIST_POLL_MS = 2500;

// A ValueMatch's `confidence` tier (see backend/recon_engine/models/
// value_mapping.py) — used to color each mapping chip so a reviewer can spot
// a shaky (medium/none) pairing at a glance without reading the tooltip.
const CONFIDENCE_LABELS = {
  very_high: "Very high",
  high: "High",
  medium: "Medium",
  none: "Unresolved",
  out_of_scope: "Out of scope",
};

// One field pair's (e.g. Material -> PRDID) batch-scoped LLM/library value
// mappings — a compact chip per resolved source value, colored by
// confidence, with the human-readable evidence as its tooltip.
function BatchMappings({ mappings }) {
  if (!mappings?.length) return null;
  return (
    <div className="stored-run-mappings">
      {mappings.map((vm) => (
        <div key={`${vm.source_field}->${vm.target_field}`} className="stored-run-mapping-group">
          <span className="stored-run-mapping-group__title">
            Value mapping: {vm.source_field} → {vm.target_field}
          </span>
          <div className="stored-run-mapping-chips">
            {vm.matches.map((m) => (
              <span
                key={m.source_value}
                className={`mapping-chip mapping-chip--${m.confidence}`}
                title={`${CONFIDENCE_LABELS[m.confidence] || m.confidence} — ${m.evidence}`}
              >
                {m.source_value} → {m.target_value ?? "—"}
                <span className="mapping-chip__count">{m.row_count}</span>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function StatusCell({ run }) {
  if (run.status === "running") {
    return (
      <span className="stored-run-running">
        <span className="stored-run-running__pulse">
          <span className="stored-run-running__dot" />
          <span className="stored-run-running__dot" />
        </span>
        <span className="stored-run-running__label">Running</span>
      </span>
    );
  }
  if (run.status === "suspended") {
    return <span>{formatDate(run.suspended_at)}</span>;
  }
  return <span>{STATUS_LABELS[run.status] || run.status || "—"}</span>;
}

function ProgressCell({ run }) {
  const bp = run.batch_progress;
  if (bp && ACTIVE_STATUSES.has(run.status)) {
    return (
      <span>
        Batch {bp.batches_completed} of {bp.batch_count}
        {bp.stage ? ` — ${bp.stage.replace(/_/g, " ")}` : ""}
      </span>
    );
  }
  return (
    <span>
      {run.batches_total
        ? `Batch ${run.batches_completed} of ${run.batches_total}`
        : `${run.batches_completed} batch(es) completed`}
    </span>
  );
}

function deleteMessage(run) {
  if (!run) return "";
  const label = run.name || run.graph_run_id;
  if (run.status === "completed") {
    const total = run.batches_total ?? run.batches_completed;
    return `"${label}" finished all ${total} batch(es). Deleting removes it from Stored Runs. Download its results first if you haven't — this cannot be undone.`;
  }
  const progress = run.batches_total
    ? `completed ${run.batches_completed} of ${run.batches_total} batches`
    : `completed ${run.batches_completed} batch(es)`;
  return `"${label}" has ${progress}. Deleting removes its progress, partial results, and provisional mappings. This cannot be undone.`;
}

function StoredRunsPage() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const [pendingDelete, setPendingDelete] = useState(null);
  const [staleResume, setStaleResume] = useState(null); // { graphRunId, message }
  const [viewing, setViewing] = useState(null); // { run, result, batches, batches_completed, batches_total }

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

  // Live progress: re-fetch the whole list on a fixed interval, but only when
  // something is actually active — a ref (not `runs` itself) is read inside
  // the tick so the interval is set up once rather than torn down/recreated
  // on every fetch. One list-level poll rather than one poll per row: self-
  // corrects if a row appears/disappears, no per-row timer bookkeeping.
  const runsRef = useRef(runs);
  useEffect(() => {
    runsRef.current = runs;
  }, [runs]);
  useEffect(() => {
    const interval = setInterval(() => {
      if (runsRef.current.some((r) => ACTIVE_STATUSES.has(r.status))) {
        load();
      }
    }, LIST_POLL_MS);
    return () => clearInterval(interval);
  }, [load]);

  // Active runs first (stable sort preserves each group's existing order).
  const sortedRuns = useMemo(
    () => [...runs].sort((a, b) => (ACTIVE_STATUSES.has(a.status) ? 0 : 1) - (ACTIVE_STATUSES.has(b.status) ? 0 : 1)),
    [runs],
  );

  const doResume = async (graphRunId, { force = false } = {}) => {
    setBusyId(graphRunId);
    setError(null);
    try {
      await resumeRun(graphRunId, { force });
      setStaleResume(null);
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
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't load results for this run.");
    } finally {
      setBusyId(null);
    }
  };

  const download = (run) => {
    if (run.status === "completed") {
      window.open(getComparisonUrl(run.graph_run_id), "_blank");
    } else {
      exportPartialResults(run.graph_run_id);
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
            at, or view/export what they'd already completed. A run stays listed here, with live
            progress while it runs, until you delete it.
          </p>
        </div>
        <span className="ct-card__spacer" />
        <Button type="button" variant="outline" size="sm" onClick={load} disabled={loading}>
          <FiRefreshCw /> Refresh
        </Button>
      </div>

      {error && <Alert variant="error">{error}</Alert>}
      {loading && !runs.length && <p>Loading…</p>}
      {!loading && !runs.length && (
        <p style={{ color: "#64748b" }}>
          Nothing here yet. Suspend an in-progress reconciliation run to park it for later.
        </p>
      )}

      {sortedRuns.length > 0 && (
        <div className="ct-table-wrap">
          <table className="ct-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Reason</th>
                <th>Progress</th>
                <th>Expires</th>
                <th aria-label="Row actions" />
              </tr>
            </thead>
            <tbody>
              {sortedRuns.map((run) => {
                const active = ACTIVE_STATUSES.has(run.status);
                return (
                  <tr key={run.graph_run_id}>
                    <td>
                      <div>{run.name || run.graph_run_id}</div>
                      <code style={{ fontSize: 12, color: "#94a3b8" }}>{run.graph_run_id}</code>
                    </td>
                    <td>
                      <StatusCell run={run} />
                    </td>
                    <td>{run.suspend_reason || "—"}</td>
                    <td>
                      <ProgressCell run={run} />
                    </td>
                    <td>{formatDate(run.expires_at)}</td>
                    <td style={{ display: "flex", gap: 4 }}>
                      {run.status === "suspended" && (
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
                      )}
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
                        onClick={() => download(run)}
                        disabled={busyId === run.graph_run_id}
                        aria-label={run.status === "completed" ? "Download results" : "Export partial results"}
                      >
                        <FiDownload />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-8 text-xs"
                        onClick={() => setPendingDelete(run)}
                        disabled={busyId === run.graph_run_id || active}
                        title={active ? "Wait for the run to finish before deleting it." : undefined}
                        aria-label="Delete stored run"
                      >
                        <FiTrash2 />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={Boolean(viewing)}
        onClose={() => setViewing(null)}
        title={`Partial results — ${viewing?.run?.name || viewing?.run?.graph_run_id || ""}`}
        className="max-w-[95vw] w-[95vw] sm:max-w-[1400px]"
      >
        {viewing && (
          <div>
            {viewing.result && (
              <p className="wizard-field__help" style={{ marginTop: 0 }}>
                {viewing.result.summary?.match ?? 0} matched / {viewing.result.summary?.total ?? 0} total
                rows across {viewing.batches_completed} of {viewing.batches_total ?? "?"} batches completed
                so far.
              </p>
            )}
            {viewing.batches_completed === 0 ? (
              <div className="stored-run-empty-state">No data available yet.</div>
            ) : (
              <div className="stored-run-batch-grid">
                {viewing.batches.map((batch) => (
                  <div key={batch.batch_index} className="stored-run-batch-card">
                    <div className="stored-run-batch-card__head">
                      <span className="stored-run-batch-card__title">
                        Batch {batch.batch_index + 1} — {batch.batch_label}
                      </span>
                      <span className="stored-run-batch-card__hint">{batch.row_count} row(s)</span>
                    </div>
                    <BatchMappings mappings={batch.mappings} />
                    {batch.preview_rows.length > 0 ? (
                      <div className="ct-table-wrap">
                        <table className="ct-table">
                          <thead>
                            <tr>
                              <th>Business key</th>
                              <th>Classification</th>
                              <th>Differences</th>
                              <th>Record</th>
                            </tr>
                          </thead>
                          <tbody>
                            {batch.preview_rows.map((row, i) => {
                              const cls = ROW_CLASS[row.classification] ?? {
                                label: row.classification,
                                variant: "default",
                              };
                              return (
                                <tr key={row.record_id ?? i}>
                                  <td className="mono">{row.business_key}</td>
                                  <td>
                                    <Badge variant={cls.variant}>{cls.label}</Badge>
                                  </td>
                                  <td>
                                    <FieldDiffs diffs={row.field_diffs} />
                                  </td>
                                  <td>{row.record_id ? <ShortId value={row.record_id} /> : "—"}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="wizard-field__help" style={{ margin: 0 }}>
                        No records fell in this batch's window.
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        title="Delete stored run"
        message={deleteMessage(pendingDelete)}
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
