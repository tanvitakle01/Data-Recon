import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Alert } from "@bristlecone/canopy";
import { FiTrash2, FiRefreshCw, FiAlertTriangle } from "react-icons/fi";
import api from "../services/api";
import styles from "./library.module.css";

function isKeyRole(role) {
  return /key/i.test(String(role));
}

// Reconciled field (column→column) mappings — reused automatically when the
// same source + target column set reappears.
function AttributeMappingSection({ onCount }) {
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

  const didInit = useRef(false);
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    load();
  }, [load]);

  useEffect(() => {
    onCount?.(all.length);
  }, [all, onCount]);

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

  const remove = async (m) => {
    const n = m.mappings?.length ?? 0;
    const note = n > 1 ? ` This removes all ${n} column pairings stored for this connector pair.` : "";
    if (!window.confirm(`Delete this stored mapping?${note} This cannot be undone.`)) return;
    setBusyId(m.id);
    try {
      await api.delete(`/api/recon/library/${m.id}`);
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
    <section className="ct-card">
      <div className="ct-card__head">
        <h3 className="ct-card__title">Field mappings</h3>
        <span className="ct-card__spacer" />
        <Button type="button" variant="outline" size="sm" onClick={load} disabled={loading}>
          <FiRefreshCw /> Refresh
        </Button>
        <Button type="button" variant="destructive" size="sm" onClick={flush} disabled={loading || !all.length}>
          <FiAlertTriangle /> Flush library
        </Button>
      </div>

      <div className="ct-card__body">
        <p className="wizard-field__help" style={{ marginTop: 0 }}>
          Reconciled field (column→column) mappings, reused automatically when the same source +
          target column set reappears. Field mapping only — value mapping lives in the Value Pairs
          tab.
        </p>

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

        {error && <Alert variant="error">{error}</Alert>}
        {loading && !all.length && <p className={styles.empty}>Loading…</p>}
        {!loading && !rows.length && (
          <p className={styles.empty}>
            {all.length
              ? "No mappings match the current filters."
              : "The library is empty. Complete a reconciliation run to store its field mapping here."}
          </p>
        )}
      </div>

      {rows.length > 0 && (
        <div className="ct-table-wrap">
          <table className="ct-table">
            <thead>
              <tr>
                <th>Source connector</th>
                <th>Target connector</th>
                <th>Comparison type</th>
                <th>Source column</th>
                <th>Target column</th>
                <th aria-label="Row actions" />
              </tr>
            </thead>
            <tbody>
              {rows.flatMap((m) => {
                const pairings = m.mappings?.length ? m.mappings : [null];
                return pairings.map((p, i) => (
                  <tr key={`${m.id}-${i}`}>
                    <td>{m.source_connector}</td>
                    <td>{m.target_connector}</td>
                    <td>{m.comparison_type}</td>
                    <td>{p ? <code>{p.source_col}</code> : "—"}</td>
                    <td>
                      {p ? (
                        <>
                          <code>{p.target_col}</code>
                          <span className={styles.role}>{isKeyRole(p.role) ? "🔑" : "📊"}</span>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-8 text-xs"
                        onClick={() => remove(m)}
                        disabled={busyId === m.id}
                        aria-label="Delete mapping"
                      >
                        <FiTrash2 />
                      </Button>
                    </td>
                  </tr>
                ));
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// value_pair_library rows are proposed by a run's LLM pairing step, already
// deterministically verified, and persisted automatically — reused (no LLM
// call) by future runs' library-first lookup (recon_engine.value_pairing.pipeline).
function ValuePairsSection({ onCount }) {
  const [all, setAll] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [filters, setFilters] = useState({ source_connector: "", target_connector: "" });

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

  const didInit = useRef(false);
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    load();
  }, [load]);

  useEffect(() => {
    onCount?.(all.length);
  }, [all, onCount]);

  const options = useMemo(() => {
    const uniq = (key) => Array.from(new Set(all.map((p) => p[key]).filter(Boolean))).sort();
    return {
      source_connector: uniq("source_connector"),
      target_connector: uniq("target_connector"),
    };
  }, [all]);

  const rows = useMemo(
    () => all.filter((p) => Object.entries(filters).every(([k, v]) => !v || p[k] === v)),
    [all, filters],
  );

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
        "Flush the ENTIRE value-pair library?\n\nThis permanently deletes every stored value pair so future runs re-derive them via the LLM. This cannot be undone.",
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
    <section className="ct-card">
      <div className="ct-card__head">
        <h3 className="ct-card__title">Value pairs</h3>
        <span className="ct-card__spacer" />
        <Button type="button" variant="outline" size="sm" onClick={load} disabled={loading}>
          <FiRefreshCw /> Refresh
        </Button>
        <Button type="button" variant="destructive" size="sm" onClick={flush} disabled={loading || !all.length}>
          <FiAlertTriangle /> Flush library
        </Button>
      </div>

      <div className="ct-card__body">
        <p className="wizard-field__help" style={{ marginTop: 0 }}>
          LLM-proposed, deterministically-verified source→target value pairs (e.g. Material → PRDID),
          persisted automatically and reused with no LLM call on future runs.
        </p>

        <div className={styles.filters}>
          {["source_connector", "target_connector"].map((key) => (
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

        {error && <Alert variant="error">{error}</Alert>}
        {loading && !all.length && <p className={styles.empty}>Loading…</p>}
        {!loading && !rows.length && (
          <p className={styles.empty}>
            {all.length
              ? "No value pairs match the current filters."
              : "The value-pair library is empty. Run Deterministic Mapping to propose pairs here."}
          </p>
        )}
      </div>

      {rows.length > 0 && (
        <div className="ct-table-wrap">
          <table className="ct-table">
            <thead>
              <tr>
                <th>Source connector</th>
                <th>Target connector</th>
                <th>Source field</th>
                <th>Target field</th>
                <th>Source value</th>
                <th>Target value</th>
                <th>Transformation applied</th>
                <th aria-label="Row actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td>{p.source_connector}</td>
                  <td>{p.target_connector}</td>
                  <td>
                    <code>{p.source_field}</code>
                  </td>
                  <td>
                    <code>{p.target_field}</code>
                  </td>
                  <td>
                    <code>{p.source_value}</code>
                  </td>
                  <td>
                    <code>{p.target_value}</code>
                  </td>
                  <td className={styles.muted}>
                    {(p.ops ?? []).map((s) => `${s.op}(${JSON.stringify(s.params)})`).join(" → ") || "—"}
                  </td>
                  <td>
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
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function LibraryPage() {
  const [tab, setTab] = useState("fields");
  const [fieldCount, setFieldCount] = useState(0);
  const [valueCount, setValueCount] = useState(0);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Mapping Library</h1>
          <p className={styles.subtitle}>
            Stored field mappings and value pairs, reused automatically when the same connector
            pair and dataset type reappear.
          </p>
        </div>
      </div>

      <div className="ct-tabs">
        <button type="button" className={tab === "fields" ? "is-active" : ""} onClick={() => setTab("fields")}>
          Field mappings<span className="ct-tabs button__count">{fieldCount}</span>
        </button>
        <button type="button" className={tab === "values" ? "is-active" : ""} onClick={() => setTab("values")}>
          Value pairs<span className="ct-tabs button__count">{valueCount}</span>
        </button>
      </div>

      <div style={{ marginTop: 16 }}>
        {tab === "fields" ? (
          <AttributeMappingSection onCount={setFieldCount} />
        ) : (
          <ValuePairsSection onCount={setValueCount} />
        )}
      </div>
    </div>
  );
}
