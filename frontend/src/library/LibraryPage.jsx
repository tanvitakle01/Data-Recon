import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Badge } from "@bristlecone/canopy";
import { FiTrash2, FiRefreshCw, FiAlertTriangle, FiCheck, FiX } from "react-icons/fi";
import api from "../services/api";
import styles from "./library.module.css";

// Mirrors the per-row provenance vocabulary the mapping card uses.
const PROV_BADGE = {
  library: { label: "Vector Library", variant: "info" },
  groq: { label: "Groq", variant: "default" },
  openai: { label: "OpenAI", variant: "default" },
  manual: { label: "Manual", variant: "warning" },
};

const STATUS_BADGE = {
  pending: { label: "Pending", variant: "warning" },
  approved: { label: "Approved", variant: "success" },
  rejected: { label: "Rejected", variant: "error" },
};

function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString();
}

function isKeyRole(role) {
  return /key/i.test(String(role));
}

// Reconciled field (column→column) mappings — reused automatically when the
// same source + target column set reappears.
function AttributeMappingSection() {
  const [all, setAll] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [filters, setFilters] = useState({ source_connector: "", target_connector: "", comparison_type: "" });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get("/api/recon/library");
      setAll(res.data?.mappings ?? []);
    } catch {
      setError("Failed to load the library.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Filter options come from the full snapshot so narrowing one filter never
  // hides the others' choices.
  const options = useMemo(() => {
    const uniq = (key) => Array.from(new Set(all.map((m) => m[key]).filter(Boolean))).sort();
    return {
      source_connector: uniq("source_connector"),
      target_connector: uniq("target_connector"),
      comparison_type: uniq("comparison_type"),
    };
  }, [all]);

  const rows = useMemo(
    () => all.filter((m) => Object.entries(filters).every(([k, v]) => !v || m[k] === v)),
    [all, filters],
  );

  const remove = async (id) => {
    if (!window.confirm("Delete this stored mapping? This cannot be undone.")) return;
    setBusyId(id);
    try {
      await api.delete(`/api/recon/library/${id}`);
      await load();
    } catch {
      setError("Delete failed.");
    } finally {
      setBusyId(null);
    }
  };

  const flush = async () => {
    if (
      !window.confirm(
        "Flush the ENTIRE attribute-mapping library?\n\nThis permanently deletes every stored mapping so the next run starts cold (LLM). This cannot be undone.",
      )
    )
      return;
    setLoading(true);
    try {
      await api.post("/api/recon/library/flush", null, { params: { confirm: true } });
      await load();
    } catch {
      setError("Flush failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Mapping Library</h1>
          <p className={styles.subtitle}>
            Reconciled field (column→column) mappings, reused automatically when the same
            source + target column set reappears. Field mapping only — value mapping lives in the
            Value Pair Library below.
          </p>
        </div>
        <div className={styles.headerActions}>
          <Button type="button" variant="ghost" onClick={load} disabled={loading}>
            <FiRefreshCw /> Refresh
          </Button>
          <Button type="button" variant="destructive" onClick={flush} disabled={loading || !all.length}>
            <FiAlertTriangle /> Flush library
          </Button>
        </div>
      </div>

      <div className={styles.filters}>
        {["source_connector", "target_connector", "comparison_type"].map((key) => (
          <label key={key} className={styles.filter}>
            <span className={styles.filterLabel}>{key.replace(/_/g, " ")}</span>
            <select
              className={styles.select}
              value={filters[key]}
              onChange={(e) => setFilters((f) => ({ ...f, [key]: e.target.value }))}
            >
              <option value="">All</option>
              {options[key].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      {error && <p className={styles.error}>{error}</p>}

      {loading && !all.length ? (
        <p className={styles.empty}>Loading…</p>
      ) : !rows.length ? (
        <p className={styles.empty}>
          {all.length
            ? "No mappings match the current filters."
            : "The library is empty. Complete a reconciliation run to store its field mapping here."}
        </p>
      ) : (
        <div className="surface-elevated">
          <table className={`table-elevated ${styles.table}`}>
            <thead>
              <tr>
                <th>Source → Target</th>
                <th>Comparison</th>
                <th>Column pairings</th>
                <th>Provenance</th>
                <th>Added by</th>
                <th>Last used</th>
                <th aria-label="Row actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => {
                const prov = PROV_BADGE[m.provenance] ?? { label: m.provenance, variant: "default" };
                return (
                  <tr key={m.id}>
                    <td className={styles.connectors}>
                      <span>{m.source_connector}</span>
                      <span className={styles.arrow}>→</span>
                      <span>{m.target_connector}</span>
                    </td>
                    <td>{m.comparison_type}</td>
                    <td>
                      <ul className={styles.pairs}>
                        {m.mappings.map((p, i) => (
                          <li key={`${p.source_col}-${p.target_col}-${i}`}>
                            <code>{p.source_col}</code>
                            <span className={styles.arrow}>→</span>
                            <code>{p.target_col}</code>
                            <span className={styles.role}>{isKeyRole(p.role) ? "🔑" : "📊"}</span>
                          </li>
                        ))}
                      </ul>
                    </td>
                    <td>
                      <Badge variant={prov.variant}>{prov.label}</Badge>
                    </td>
                    <td>
                      <div>{m.added_by}</div>
                      <div className={styles.muted}>{fmtDate(m.added_on)}</div>
                    </td>
                    <td>{fmtDate(m.last_used_on)}</td>
                    <td>
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-8 text-xs"
                        onClick={() => remove(m.id)}
                        disabled={busyId === m.id}
                        aria-label="Delete mapping"
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
    </div>
  );
}

// Approved value_pair_library rows are reused (no LLM call) by future runs'
// library-first lookup (recon_engine.value_pairing.pipeline); PENDING rows
// were proposed by a run's LLM pairing step and already deterministically
// verified — approving/rejecting here only decides reuse by FUTURE runs.
function ValuePairsSection() {
  const [all, setAll] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [filters, setFilters] = useState({ source_connector: "", target_connector: "", status: "" });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get("/api/recon/value-pairs");
      setAll(res.data?.pairs ?? []);
    } catch {
      setError("Failed to load the value-pair library.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const options = useMemo(() => {
    const uniq = (key) => Array.from(new Set(all.map((p) => p[key]).filter(Boolean))).sort();
    return {
      source_connector: uniq("source_connector"),
      target_connector: uniq("target_connector"),
      status: uniq("status"),
    };
  }, [all]);

  const rows = useMemo(
    () => all.filter((p) => Object.entries(filters).every(([k, v]) => !v || p[k] === v)),
    [all, filters],
  );

  const act = async (id, action) => {
    setBusyId(id);
    try {
      await api.post(`/api/recon/value-pairs/${id}/${action}`);
      await load();
    } catch {
      setError(`${action === "approve" ? "Approve" : "Reject"} failed.`);
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this stored value pair? This cannot be undone.")) return;
    setBusyId(id);
    try {
      await api.delete(`/api/recon/value-pairs/${id}`);
      await load();
    } catch {
      setError("Delete failed.");
    } finally {
      setBusyId(null);
    }
  };

  const flush = async () => {
    if (
      !window.confirm(
        "Flush the ENTIRE value-pair library?\n\nThis permanently deletes every stored value pair (pending, approved, and rejected) so future runs re-derive them via the LLM. This cannot be undone.",
      )
    )
      return;
    setLoading(true);
    try {
      await api.post("/api/recon/value-pairs/flush", null, { params: { confirm: true } });
      await load();
    } catch {
      setError("Flush failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.section}>
      <div className={styles.header}>
        <div>
          <h2 className={styles.sectionTitle}>Value Pair Library</h2>
          <p className={styles.subtitle}>
            LLM-proposed, deterministically-verified source→target value pairs (e.g. Material →
            PRDID). Approved pairs are reused with no LLM call on future runs; pending pairs still
            applied to the run that proposed them, but need approval here to be reused.
          </p>
        </div>
        <div className={styles.headerActions}>
          <Button type="button" variant="ghost" onClick={load} disabled={loading}>
            <FiRefreshCw /> Refresh
          </Button>
          <Button type="button" variant="destructive" onClick={flush} disabled={loading || !all.length}>
            <FiAlertTriangle /> Flush library
          </Button>
        </div>
      </div>

      <div className={styles.filters}>
        {["source_connector", "target_connector", "status"].map((key) => (
          <label key={key} className={styles.filter}>
            <span className={styles.filterLabel}>{key.replace(/_/g, " ")}</span>
            <select
              className={styles.select}
              value={filters[key]}
              onChange={(e) => setFilters((f) => ({ ...f, [key]: e.target.value }))}
            >
              <option value="">All</option>
              {options[key].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      {error && <p className={styles.error}>{error}</p>}

      {loading && !all.length ? (
        <p className={styles.empty}>Loading…</p>
      ) : !rows.length ? (
        <p className={styles.empty}>
          {all.length
            ? "No value pairs match the current filters."
            : "The value-pair library is empty. Run Deterministic Mapping to propose pairs here."}
        </p>
      ) : (
        <div className="surface-elevated">
          <table className={`table-elevated ${styles.table}`}>
            <thead>
              <tr>
                <th>Source → Target</th>
                <th>Field</th>
                <th>Value pair</th>
                <th>Transform</th>
                <th>Status</th>
                <th>Added</th>
                <th aria-label="Row actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const status = STATUS_BADGE[p.status] ?? { label: p.status, variant: "default" };
                return (
                  <tr key={p.id}>
                    <td className={styles.connectors}>
                      <span>{p.source_connector}</span>
                      <span className={styles.arrow}>→</span>
                      <span>{p.target_connector}</span>
                    </td>
                    <td>
                      <code>{p.source_field}</code>
                      <span className={styles.arrow}>→</span>
                      <code>{p.target_field}</code>
                    </td>
                    <td>
                      <code>{p.source_value}</code>
                      <span className={styles.arrow}>→</span>
                      <code>{p.target_value}</code>
                    </td>
                    <td className={styles.muted}>
                      {(p.ops ?? []).map((s) => `${s.op}(${JSON.stringify(s.params)})`).join(" → ")}
                    </td>
                    <td>
                      <Badge variant={status.variant}>{status.label}</Badge>
                    </td>
                    <td>
                      <div>{p.added_by}</div>
                      <div className={styles.muted}>{fmtDate(p.added_on)}</div>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 4 }}>
                        {p.status === "pending" && (
                          <>
                            <Button
                              type="button"
                              variant="ghost"
                              className="h-8 text-xs"
                              onClick={() => act(p.id, "approve")}
                              disabled={busyId === p.id}
                              aria-label="Approve pair"
                            >
                              <FiCheck />
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              className="h-8 text-xs"
                              onClick={() => act(p.id, "reject")}
                              disabled={busyId === p.id}
                              aria-label="Reject pair"
                            >
                              <FiX />
                            </Button>
                          </>
                        )}
                        <Button
                          type="button"
                          variant="ghost"
                          className="h-8 text-xs"
                          onClick={() => remove(p.id)}
                          disabled={busyId === p.id}
                          aria-label="Delete pair"
                        >
                          <FiTrash2 />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function LibraryPage() {
  return (
    <div className={styles.page}>
      <AttributeMappingSection />
      <ValuePairsSection />
    </div>
  );
}
