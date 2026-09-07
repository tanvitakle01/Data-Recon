import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Alert } from "@bristlecone/canopy";
import { FiTrash2, FiRefreshCw, FiAlertTriangle } from "react-icons/fi";
import api from "../services/api";
import { resolveUploadConnector } from "./connectorGuess";
import styles from "./library.module.css";

function isKeyRole(role) {
  return /key/i.test(String(role));
}

// Renders a connector value as-is, except a literal "upload" gets relabeled
// when the row's own field names carry a strong naming-convention signal (see
// connectorGuess.js) — flagged via title rather than presented as confirmed.
function ConnectorCell({ value, fieldNames }) {
  const { label, inferred } = resolveUploadConnector(value, fieldNames);
  if (!inferred) return label;
  return <span title={`Inferred from field names — stored as "upload"`}>{label}</span>;
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

  const didInit = useRef(false);
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
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
                const sourceFieldNames = pairings.map((p) => p?.source_col);
                const targetFieldNames = pairings.map((p) => p?.target_col);
                return pairings.map((p, i) => (
                  <tr key={`${m.id}-${i}`}>
                    <td>
                      <ConnectorCell value={m.source_connector} fieldNames={sourceFieldNames} />
                    </td>
                    <td>
                      <ConnectorCell value={m.target_connector} fieldNames={targetFieldNames} />
                    </td>
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
function ValuePairsSection() {
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
                  <td>
                    <ConnectorCell value={p.source_connector} fieldNames={[p.source_field]} />
                  </td>
                  <td>
                    <ConnectorCell value={p.target_connector} fieldNames={[p.target_field]} />
                  </td>
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

// Plain-language wording for the allow-listed operation registry
// (backend/recon_engine/operations/registry.py). Keyed by operation name; any
// operation added there without an entry here falls back to its registry
// description, so the table is never incomplete.
const TRANSFORMATION_DEFINITIONS = {
  identity_cast_string: "Converts the field's values to text, leaving blanks blank.",
  trim_string: "Removes spaces from the start and end of a value.",
  numeric_cast: "Converts text to a number; anything unreadable becomes blank.",
  date_parse: "Reads a date in a given format and rewrites it in one standard format.",
  rename_field: "Renames a column. The values themselves are untouched.",
  prepend_prefix: "Adds fixed text to the front of every value (5006 → PL5006).",
  append_suffix: "Adds fixed text to the end of every value (5006 → 5006@S21400).",
  remove_leading_zeros: "Drops padding zeros from the number inside a value (005006 → 5006).",
  replace_value: "Swaps one piece of text for another inside the value.",
  uppercase: "Converts text to upper case.",
  lowercase: "Converts text to lower case.",
  substring: "Keeps only part of a value, chosen by start position and length.",
  regex_replace: "Rewrites the value using a search pattern and a replacement.",
  concat_fields: "Joins several columns into one new column, with a separator between them.",
  decimal_round: "Rounds a number to a set number of decimal places.",
  null_to_default: "Fills blank values with a default you choose.",
  value_mapping: "Replaces whole values using a lookup list (e.g. EA → PC).",
  conditional_prefix: "Adds a prefix only to the rows that meet a condition.",
  conditional_suffix: "Adds a suffix only to the rows that meet a condition.",
  date_format: "Same as Date parse — reformats a date into one standard format.",
  split_field: "Splits a value on a separator and keeps one of the parts.",
  convert_uom: "Converts units by multiplying or dividing by a fixed factor.",
  calculated_column: "Builds a new column from a formula over existing columns.",
  reject_null: "Drops rows where the field is blank.",
  exclude_value: "Drops rows whose field matches any of the listed values.",
  include_value: "Keeps only the rows whose field matches one of the listed values.",
  group_by: "Collapses the data to one row per unique key combination.",
  sum_aggregate: "Totals the field for each key combination.",
  deduplicate: "Removes duplicate rows for a key, keeping either the first or the last.",
  aggregate_group: "Groups by one or more columns and applies sums, counts or averages in one step.",
};

function humanizeOperation(name) {
  const words = String(name).replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// The fixed allow-listed operation set a transformation recipe may use — the
// same catalogue the wizard's "Select from Transformation Library" palette
// offers, so this page can never drift from what a run can actually execute.
function TransformationsSection() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get("/api/recon/operations");
      // compare ops are reconcile-time matchers, not transformations.
      setRows((res.data?.operations ?? []).filter((o) => o.kind !== "compare"));
    } catch {
      setError("Failed to load the transformation library.");
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

  return (
    <section className="ct-card">
      <div className="ct-card__head">
        <h3 className="ct-card__title">Transformations</h3>
        <span className="ct-card__spacer" />
        <Button type="button" variant="outline" size="sm" onClick={load} disabled={loading}>
          <FiRefreshCw /> Refresh
        </Button>
      </div>

      <div className="ct-card__body">
        <p className="wizard-field__help" style={{ marginTop: 0 }}>
          Every transformation a recipe is allowed to use. This set is fixed — a run can only apply
          what is listed here.
        </p>

        {error && <Alert variant="error">{error}</Alert>}
        {loading && !rows.length && <p className={styles.empty}>Loading…</p>}
        {!loading && !rows.length && !error && (
          <p className={styles.empty}>No transformations available.</p>
        )}
      </div>

      {rows.length > 0 && (
        <div className="ct-table-wrap">
          <table className="ct-table">
            <thead>
              <tr>
                <th>Transformation</th>
                <th>Definition</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((op) => (
                <tr key={op.name}>
                  <td>
                    <div className={styles.opName}>{humanizeOperation(op.name)}</div>
                    <code className={styles.opCode}>{op.name}</code>
                  </td>
                  <td>{TRANSFORMATION_DEFINITIONS[op.name] ?? op.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const TABS = [
  { key: "fields", label: "Field mappings", render: () => <AttributeMappingSection /> },
  { key: "values", label: "Value pairs", render: () => <ValuePairsSection /> },
  { key: "transformations", label: "Transformations", render: () => <TransformationsSection /> },
];

export default function LibraryPage() {
  const [tab, setTab] = useState("fields");

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Library</h1>
          <p className={styles.subtitle}>
            Stored field mappings and value pairs, reused automatically when the same connector
            pair and dataset type reappear, plus the fixed set of transformations a recipe can
            apply.
          </p>
        </div>
      </div>

      <div className="ct-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={tab === t.key ? "is-active" : ""}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ marginTop: 16 }}>{TABS.find((t) => t.key === tab)?.render()}</div>
    </div>
  );
}
