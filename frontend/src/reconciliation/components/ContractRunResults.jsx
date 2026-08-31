// Results view for contract-driven runs (the recon_engine runtime path):
// the classification summary produced by Shadow_Source vs Raw_Target, the
// per-row exceptions already fetched for this result (`result.detail`, from
// GET /api/recon/results/{id}), a real audit trail (GET /api/recon/audit),
// and next-step actions.
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getComparisonUrl } from "../lib/reconRun";
import api from "../../services/api";
import ShortId from "../../components/ShortId";
import { Button, Badge } from "@bristlecone/canopy";
import { FieldDiffs } from "./reconRowDisplay";
import { ROW_CLASS } from "./reconRowClassification";

// Outcome -> Canopy semantic color (matches the Badge outcome language:
// match=success/green, quantity_mismatch=error/red). "mismatch" is the
// unified bucket for a business key present on only one side (source-only or
// target-only) — there's no separate Missing/Extra category anymore.
const CLASS_LABELS = [
  { key: "match", label: "Matches", color: "var(--bcone-green)" },
  { key: "quantity_mismatch", label: "Qty Mismatches", color: "var(--bcone-red)" },
  { key: "mismatch", label: "Mismatches", color: "var(--bcone-orange)" },
];

// Real, client-side aggregation over the previewed exceptions only (never the
// full result set, which isn't shipped to the browser) — counts how often
// each field differed and the total signed delta where numeric, mirroring
// the mock's "Top variance drivers" intent without assuming any
// dataset-specific field names.
function summarizeDrivers(rows) {
  const byField = new Map();
  for (const row of rows) {
    for (const d of row.field_diffs ?? []) {
      const entry = byField.get(d.field) ?? { field: d.field, records: 0, totalDelta: 0, hasDelta: false };
      entry.records += 1;
      if (d.delta != null) {
        entry.totalDelta += d.delta;
        entry.hasDelta = true;
      }
      byField.set(d.field, entry);
    }
  }
  return [...byField.values()].sort((a, b) => b.records - a.records);
}

function ContractRunResults({ result }) {
  const navigate = useNavigate();
  const summary = result?.summary ?? {};
  const run = result?.run ?? {};
  const runId = result?.run_id ?? run.run_id;
  const previewRows = useMemo(() => result?.detail?.preview_rows ?? [], [result]);
  const exceptionRows = useMemo(
    () => previewRows.filter((r) => r.classification && r.classification !== "match"),
    [previewRows],
  );
  const drivers = useMemo(() => summarizeDrivers(exceptionRows), [exceptionRows]);

  const [tab, setTab] = useState("exceptions");
  // null = not loaded yet (renders as loading); [] = loaded, no events.
  const [auditEvents, setAuditEvents] = useState(null);
  const auditLoading = auditEvents === null;

  useEffect(() => {
    if (!runId) return undefined;
    let cancelled = false;
    api
      .get("/api/recon/audit", { params: { entity_id: runId } })
      .then((res) => {
        if (!cancelled) setAuditEvents(res.data?.events ?? []);
      })
      .catch(() => {
        if (!cancelled) setAuditEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const downloadComparison = () => {
    if (!runId) return;
    window.open(getComparisonUrl(runId), "_blank");
  };

  const total = summary.total ?? 0;
  const pct = (n) => (total ? Math.round((n / total) * 100) : 0);

  return (
    <div className="ct-col">
      {/* Post-run actions — outcomes and next steps first (business users). */}
      <div className="contract-actions results-actions">
        <ShortId value={runId} prefix="Run " />
        <Button
          type="button"
          variant="primary"
          onClick={() => runId && navigate(`/insights/run/${runId}`)}
          disabled={!runId}
        >
          View Insights
        </Button>
        <Button type="button" variant="outline" onClick={downloadComparison} disabled={!runId}>
          Download Comparison Sheet
        </Button>
      </div>

      {/* KPI band: real summary counts + a proportional outcome bar. */}
      <div className="ct-kpi-band">
        <div className="ct-kpi-band__grid">
          <div className="ct-kpi-band__cell">
            <p className="ct-kpi-card__label">Records compared</p>
            <div className="ct-kpi-card__row">
              <span className="ct-kpi-band__value">{total}</span>
            </div>
            <p className="ct-kpi-band__note">Business keys present on either side</p>
          </div>
          {CLASS_LABELS.map(({ key, label, color }) => (
            <div className="ct-kpi-band__cell" key={key}>
              <p className="ct-kpi-card__label">{label}</p>
              <div className="ct-kpi-card__row">
                <span className="ct-kpi-band__value" style={{ color }}>
                  {summary[key] ?? 0}
                </span>
                <span className="ct-kpi-card__sub">{pct(summary[key] ?? 0)}%</span>
              </div>
            </div>
          ))}
        </div>
        {total > 0 && (
          <div className="ct-kpi-band__bar">
            <span style={{ width: `${pct(summary.match)}%`, background: "var(--bcone-green)" }} />
            <span
              style={{ width: `${pct(summary.quantity_mismatch)}%`, background: "var(--bcone-red)" }}
            />
            <span style={{ width: `${pct(summary.mismatch)}%`, background: "var(--bcone-orange)" }} />
          </div>
        )}
      </div>
      <p className="wizard-field__help" style={{ marginTop: 0 }}>
        Matches include tolerance matches — fields compared with a tolerance count as a match when
        within the allowed difference.
      </p>

      <div className="ct-tabs">
        <button type="button" className={tab === "summary" ? "is-active" : ""} onClick={() => setTab("summary")}>
          Summary
        </button>
        <button
          type="button"
          className={tab === "exceptions" ? "is-active" : ""}
          onClick={() => setTab("exceptions")}
        >
          Exceptions<span className="ct-tabs button__count">{exceptionRows.length}</span>
        </button>
        <button type="button" className={tab === "audit" ? "is-active" : ""} onClick={() => setTab("audit")}>
          Audit trail<span className="ct-tabs button__count">{auditEvents?.length ?? 0}</span>
        </button>
      </div>

      {tab === "summary" && (
        <section className="ct-card">
          <div className="ct-card__head">
            <h3 className="ct-card__title">Top variance drivers</h3>
            <span className="ct-card__spacer" />
            <span className="ct-card__hint">From the previewed exceptions ({exceptionRows.length} rows)</span>
          </div>
          <div className="ct-table-wrap">
            <table className="ct-table">
              <thead>
                <tr>
                  <th>Field</th>
                  <th style={{ textAlign: "right" }}>Records</th>
                  <th style={{ textAlign: "right" }}>Net Δ</th>
                </tr>
              </thead>
              <tbody>
                {drivers.map((d) => (
                  <tr key={d.field}>
                    <td className="mono">{d.field}</td>
                    <td style={{ textAlign: "right" }}>{d.records}</td>
                    <td style={{ textAlign: "right" }} className="mono">
                      {d.hasDelta ? d.totalDelta : "—"}
                    </td>
                  </tr>
                ))}
                {drivers.length === 0 && (
                  <tr>
                    <td colSpan={3} className="wizard-field__help">
                      No field-level differences in the previewed rows.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "exceptions" && (
        <section className="ct-card">
          <div className="ct-card__head">
            <h3 className="ct-card__title">Exceptions</h3>
            <span className="ct-card__spacer" />
            <span className="ct-card__hint">
              {exceptionRows.length} of {previewRows.length} previewed rows
            </span>
          </div>
          <div className="ct-table-wrap">
            <table className="ct-table">
              <thead>
                <tr>
                  <th>Business key</th>
                  <th>Classification</th>
                  <th>Differences</th>
                  <th>Detail</th>
                  <th>Record</th>
                </tr>
              </thead>
              <tbody>
                {exceptionRows.map((row, i) => {
                  const cls = ROW_CLASS[row.classification] ?? { label: row.classification, variant: "default" };
                  return (
                    <tr key={row.business_key ?? i}>
                      <td className="mono">{row.business_key}</td>
                      <td>
                        <Badge variant={cls.variant}>{cls.label}</Badge>
                      </td>
                      <td>
                        <FieldDiffs diffs={row.field_diffs} />
                      </td>
                      <td>{row.detail}</td>
                      {/* record_id is only stamped on Auto-mode streaming rows
                          (see auto_pipeline/nodes.py) — blank for Manual mode,
                          which has no per-row batch identity to report. */}
                      <td>{row.record_id ? <ShortId value={row.record_id} /> : "—"}</td>
                    </tr>
                  );
                })}
                {exceptionRows.length === 0 && (
                  <tr>
                    <td colSpan={5} className="wizard-field__help">
                      No exceptions in the previewed rows.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "audit" && (
        <section className="ct-card">
          <div className="ct-card__head">
            <h3 className="ct-card__title">Run audit trail</h3>
            <span className="ct-card__spacer" />
            <ShortId value={runId} prefix="Run " />
          </div>
          <div className="ct-table-wrap">
            <table className="ct-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Event</th>
                  <th>Actor</th>
                  <th>Reference</th>
                </tr>
              </thead>
              <tbody>
                {(auditEvents ?? []).map((e) => (
                  <tr key={e.event_id}>
                    <td className="mono">{new Date(e.timestamp).toLocaleString()}</td>
                    <td>{e.action}</td>
                    <td>{e.actor}</td>
                    <td className="mono">{e.entity_id}</td>
                  </tr>
                ))}
                {auditLoading && (
                  <tr>
                    <td colSpan={4} className="wizard-field__help">
                      Loading audit trail…
                    </td>
                  </tr>
                )}
                {!auditLoading && auditEvents.length === 0 && (
                  <tr>
                    <td colSpan={4} className="wizard-field__help">
                      No audit events recorded for this run.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

export default ContractRunResults;
