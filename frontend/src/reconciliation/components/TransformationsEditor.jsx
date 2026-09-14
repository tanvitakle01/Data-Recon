// Step-recipe transformation editor (Fig 4). A visual, structured authoring
// surface over the SAME contract `operations` array the executor runs — no
// parallel engine. Two panes:
//
//   left   — ordered step list, grouped by execution phase (Filters →
//            Transforms → Aggregations). Drag to reorder WITHIN a phase; a
//            step's phase is fixed by its op kind so cross-phase moves are
//            impossible (Decision B: visible order always == execution order).
//   right  — the selected step's config (field + parameters), driven by the
//            allow-listed registry's param schema.
//
// Groq is optional: "Draft steps from a description" (when the parent wires
// onDraftSteps) emits steps into the list that the user then edits. Building
// steps by hand needs no LLM. Both produce the same operations array.
//
// No embedded preview here — the merged Mapping card's Mapping Review (fed by
// the live pre-pass, see TransformationSpecStep) is the feedback surface for
// what a recipe edit changes, not a raw shadow-diff curtain on this component.
import { useEffect, useMemo, useRef, useState } from "react";
import api from "../../services/api";
import {
  PHASES,
  addStep,
  operationsToSteps,
  orderedSteps,
  phaseIndexForKind,
  removeStep,
  reorderWithinPhase,
  toggleStep,
  updateStep,
} from "../lib/recipeModel";
import { Button, Badge } from "@bristlecone/canopy";
import styles from "./recipeEditor.module.css";

// How to render each known parameter. Anything not listed falls back to text.
const PARAM_META = {
  to: { type: "text", label: "New name" },
  value: { type: "text", label: "Value" },
  from: { type: "text", label: "From" },
  default: { type: "text", label: "Default" },
  separator: { type: "text", label: "Separator" },
  into: { type: "text", label: "Into column" },
  pattern: { type: "text", label: "Pattern" },
  replacement: { type: "text", label: "Replacement" },
  source_format: { type: "text", label: "Source format", placeholder: "DD.MM.YYYY" },
  canonical_format: { type: "text", label: "Canonical format", placeholder: "YYYY-MM-DD" },
  expression: { type: "text", label: "Expression", placeholder: "ABS(A - B)" },
  start: { type: "number", label: "Start" },
  length: { type: "number", label: "Length" },
  index: { type: "number", label: "Index" },
  decimals: { type: "number", label: "Decimals" },
  factor: { type: "number", label: "Factor" },
  values: { type: "list", label: "Values" },
  fields: { type: "columns", label: "Fields" },
  by: { type: "columns", label: "Group by" },
  mapping: { type: "kv", label: "Mapping (from → to)" },
  operation: { type: "select", label: "Operation", options: ["multiply", "divide"] },
  condition: {
    type: "select",
    label: "Condition",
    options: ["non_empty", "numeric", "non_numeric", "matches"],
  },
  keep: { type: "select", label: "Keep", options: ["first", "last"] },
  aggregations: { type: "aggregations", label: "Aggregations (field + function)" },
  width: { type: "number", label: "Width" },
  granularity: {
    type: "select",
    label: "Granularity",
    options: ["day", "week", "month", "quarter", "year"],
  },
  anchor: { type: "select", label: "Anchor", options: ["start", "end"] },
  lower_offset_days: { type: "number", label: "Lower offset (days from run date)" },
  upper_offset_days: { type: "number", label: "Upper offset (days from run date)" },
  offset_days: { type: "number", label: "Offset (days from run date)" },
  // Named distinctly from `condition` above (a different value space:
  // date comparisons here vs. non_empty/numeric/matches there) so the two
  // ops never collide on the same dropdown options.
  date_condition: { type: "select", label: "Date condition", options: ["lt", "gt", "eq"] },
  compare_to: { type: "text", label: "Compare to", placeholder: "run_date or a column name" },
  weekday_exception: {
    type: "json",
    label: "Weekday exception (JSON)",
    placeholder: '{"on_weekday":"saturday","offset_days":2}',
  },
};

// aggregate_group's per-row aggregation function choices — the same
// sum/count/average/min/max vocabulary the backend's AggregationType enum uses.
const AGG_FUNCS = ["sum", "count", "average", "min", "max", "first"];

function MultiColumnSelect({ columns, value, onChange }) {
  const selected = Array.isArray(value) ? value : [];
  const toggle = (col) =>
    onChange(selected.includes(col) ? selected.filter((c) => c !== col) : [...selected, col]);
  if (!columns.length) return <p className={styles.hint}>No source columns available.</p>;
  return (
    <div className={styles.checkList}>
      {columns.map((col) => (
        <label key={col} className={styles.checkRow}>
          <input type="checkbox" checked={selected.includes(col)} onChange={() => toggle(col)} />
          {col}
        </label>
      ))}
    </div>
  );
}

function KvEditor({ value, onChange }) {
  const pairs = Object.entries(value ?? {});
  const setPair = (i, k, v) => {
    const next = pairs.map(([pk, pv], idx) => (idx === i ? [k, v] : [pk, pv]));
    onChange(Object.fromEntries(next.filter(([pk]) => pk !== "")));
  };
  const add = () => onChange({ ...(value ?? {}), "": "" });
  const remove = (i) =>
    onChange(Object.fromEntries(pairs.filter((_, idx) => idx !== i)));
  return (
    <div>
      {pairs.map(([k, v], i) => (
        <div key={i} className={styles.kvRow}>
          <input
            className={styles.input}
            placeholder="from"
            value={k}
            onChange={(e) => setPair(i, e.target.value, v)}
          />
          <input
            className={styles.input}
            placeholder="to"
            value={v}
            onChange={(e) => setPair(i, k, e.target.value)}
          />
          <button type="button" className={styles.iconBtn} onClick={() => remove(i)} title="Remove">
            ✕
          </button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={add}>
        + Add mapping
      </Button>
    </div>
  );
}

// aggregate_group's "aggregations" param: one or more {field, func} rows —
// the Aggregate half of "Aggregate & Group" (Group By is just the existing
// `by` param, rendered by MultiColumnSelect above).
function AggregationSpecEditor({ columns, value, onChange }) {
  const rows = Array.isArray(value) ? value : [];
  const setRow = (i, patch) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const add = () => onChange([...rows, { field: "", func: "sum" }]);
  const remove = (i) => onChange(rows.filter((_, idx) => idx !== i));
  return (
    <div>
      {rows.map((row, i) => (
        <div key={i} className={styles.kvRow}>
          <select
            className={styles.select}
            value={row.field ?? ""}
            onChange={(e) => setRow(i, { field: e.target.value })}
          >
            <option value="">— select column —</option>
            {columns.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select
            className={styles.select}
            value={row.func ?? "sum"}
            onChange={(e) => setRow(i, { func: e.target.value })}
          >
            {AGG_FUNCS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <button type="button" className={styles.iconBtn} onClick={() => remove(i)} title="Remove">
            ✕
          </button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={add}>
        + Add aggregation
      </Button>
    </div>
  );
}

function ParamField({ name, value, columns, onChange }) {
  const meta = PARAM_META[name] ?? { type: "text", label: name };
  const set = (v) => onChange(name, v);

  if (meta.type === "columns") {
    return (
      <div className={styles.field}>
        <label className={styles.fieldLabel}>{meta.label}</label>
        <MultiColumnSelect columns={columns} value={value} onChange={set} />
      </div>
    );
  }
  if (meta.type === "kv") {
    return (
      <div className={styles.field}>
        <label className={styles.fieldLabel}>{meta.label}</label>
        <KvEditor value={value} onChange={set} />
      </div>
    );
  }
  if (meta.type === "aggregations") {
    return (
      <div className={styles.field}>
        <label className={styles.fieldLabel}>{meta.label}</label>
        <AggregationSpecEditor columns={columns} value={value} onChange={set} />
      </div>
    );
  }
  if (meta.type === "select") {
    return (
      <div className={styles.field}>
        <label className={styles.fieldLabel}>{meta.label}</label>
        <select className={styles.select} value={value ?? ""} onChange={(e) => set(e.target.value)}>
          <option value="">—</option>
          {meta.options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </div>
    );
  }
  if (meta.type === "json") {
    // Stateless round-trip: while the typed text is valid JSON, `value` is a
    // real object/array (what the executor needs); mid-edit, an incomplete
    // literal is kept as a plain string so the field stays editable rather
    // than reverting on every keystroke.
    const text = typeof value === "string" ? value : JSON.stringify(value ?? {});
    return (
      <div className={styles.field}>
        <label className={styles.fieldLabel}>{meta.label}</label>
        <input
          className={styles.input}
          value={text}
          placeholder={meta.placeholder}
          onChange={(e) => {
            const raw = e.target.value;
            try {
              set(JSON.parse(raw));
            } catch {
              set(raw);
            }
          }}
        />
      </div>
    );
  }
  if (meta.type === "list") {
    const text = Array.isArray(value) ? value.join(", ") : value ?? "";
    return (
      <div className={styles.field}>
        <label className={styles.fieldLabel}>{meta.label}</label>
        <input
          className={styles.input}
          value={text}
          placeholder="comma, separated, values"
          onChange={(e) =>
            set(
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            )
          }
        />
      </div>
    );
  }
  return (
    <div className={styles.field}>
      <label className={styles.fieldLabel}>{meta.label}</label>
      <input
        className={styles.input}
        type={meta.type === "number" ? "number" : "text"}
        value={value ?? ""}
        placeholder={meta.placeholder}
        onChange={(e) =>
          set(meta.type === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value)
        }
      />
    </div>
  );
}

export default function RecipeEditor({
  steps,
  onChange,
  sourceColumns = [],
  onDraftSteps,
}) {
  const [catalogue, setCatalogue] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [draftDesc, setDraftDesc] = useState("");
  const [drafting, setDrafting] = useState(false);
  // The manual operation palette starts collapsed so the ~20 ops don't confront
  // the user up front — Draft Steps (AI) is the primary entry point, and the
  // library is opened on demand (its toggle or "+ Add Step").
  const [libraryOpen, setLibraryOpen] = useState(false);
  const dragRef = useRef(null); // { id, phaseKey, index }

  // Registry catalogue for the palette (compare ops excluded — reconciler-only).
  useEffect(() => {
    let cancelled = false;
    api
      .get("/api/recon/operations")
      .then((res) => {
        if (!cancelled) setCatalogue((res.data?.operations ?? []).filter((o) => o.kind !== "compare"));
      })
      .catch(() => {
        if (!cancelled) setCatalogue([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const byName = useMemo(() => new Map(catalogue.map((c) => [c.name, c])), [catalogue]);
  // Flat, execution-ordered recipe with each step's phase + within-phase index
  // attached — the list is displayed 1..N, but drag-reorder still scopes to the
  // step's own phase (cross-phase drops snap back).
  const orderedList = useMemo(() => {
    const counters = {};
    return orderedSteps(steps).map((step) => {
      const phaseKey = PHASES[phaseIndexForKind(step.kind)]?.key ?? "transform";
      const phaseIdx = counters[phaseKey] ?? 0;
      counters[phaseKey] = phaseIdx + 1;
      return { step, phaseKey, phaseIdx };
    });
  }, [steps]);
  const selected = steps.find((s) => s.id === selectedId) ?? null;
  const selectedEntry = selected ? byName.get(selected.op) : null;

  // ── step mutations ──────────────────────────────────────────────────────
  const setSteps = (next) => onChange(next);
  const handleAdd = (entry) => {
    const next = addStep(steps, entry);
    setSteps(next);
    setSelectedId(next[next.length - 1].id);
  };
  const handleRemove = (id) => {
    setSteps(removeStep(steps, id));
    if (selectedId === id) setSelectedId(null);
  };
  const setParam = (paramName, value) => {
    if (!selected) return;
    setSteps(updateStep(steps, selected.id, { params: { ...selected.params, [paramName]: value } }));
  };

  // ── drag reorder (within phase only) ───────────────────────────────────────
  const onDragStart = (id, phaseKey, index) => {
    dragRef.current = { id, phaseKey, index };
  };
  const onDrop = (phaseKey, index) => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || drag.phaseKey !== phaseKey) return; // cross-phase drop ignored (snaps back)
    setSteps(reorderWithinPhase(steps, phaseKey, drag.index, index));
  };

  const runDraftSteps = async () => {
    if (!onDraftSteps || !draftDesc.trim()) return;
    setDrafting(true);
    try {
      const operations = await onDraftSteps(draftDesc.trim());
      const drafted = operationsToSteps(operations, catalogue);
      if (drafted.length) setSteps([...steps, ...drafted]);
      setDraftDesc("");
    } finally {
      setDrafting(false);
    }
  };

  return (
    <div className={styles.editor}>
      {/* ── Left column (40%): draft (primary) · library · ordered recipe ── */}
      <div className={[styles.pane, styles.paneSteps].join(" ")}>
        <p className={styles.paneTitle}>Transformation Recipe</p>

        {/* Primary entry point — always visible. */}
        {onDraftSteps && (
          <div className={styles.field}>
            <label className={styles.fieldLabel}>Draft Steps (Optional AI)</label>
            <input
              className={styles.input}
              value={draftDesc}
              placeholder="e.g. Remove leading zeros from Plant, then prefix PL"
              onChange={(e) => setDraftDesc(e.target.value)}
            />
            <div style={{ marginTop: 6 }}>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={runDraftSteps}
                disabled={drafting || !draftDesc.trim()}
              >
                {drafting ? "Drafting…" : "Draft Steps"}
              </Button>
            </div>
            <p className={styles.hint}>Drafted steps are added below for you to edit — nothing is auto-applied.</p>
          </div>
        )}

        {/* Collapsible manual palette — all ops live here, grouped by phase. */}
        <div className={styles.library}>
          <button
            type="button"
            className={styles.libraryToggle}
            aria-expanded={libraryOpen}
            onClick={() => setLibraryOpen((v) => !v)}
          >
            <span className={styles.caret}>{libraryOpen ? "▼" : "▶"}</span>
            Select from Transformation Library
          </button>
          {libraryOpen && (
            <div className={styles.libraryBody}>
              {PHASES.map((phase) => {
                const entries = catalogue.filter((c) => c.kind === phase.kind);
                if (!entries.length) return null;
                return (
                  <div key={phase.key} className={styles.phase}>
                    <div className={styles.phaseHead}>
                      <span className={styles.phaseLabel}>{phase.label}</span>
                      <span className={styles.phaseHint}>{phase.hint}</span>
                    </div>
                    <div className={styles.palette}>
                      {entries.map((entry) => (
                        <button
                          key={entry.name}
                          type="button"
                          className={styles.paletteChip}
                          title={entry.description}
                          onClick={() => handleAdd(entry)}
                        >
                          + {entry.name}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Current recipe: single ordered list — execution order, no phase split. */}
        <div className={styles.recipe}>
          <div className={styles.phaseHead}>
            <span className={styles.phaseLabel}>Current Recipe</span>
          </div>
          {orderedList.length === 0 && (
            <p className={styles.emptyPhase}>
              No steps yet — draft from a description or add from the library.
            </p>
          )}
          {orderedList.map(({ step, phaseKey, phaseIdx }, n) => (
            <div
              key={step.id}
              className={[
                styles.step,
                selectedId === step.id ? styles.stepSelected : "",
                step.enabled ? "" : styles.stepDisabled,
              ].join(" ")}
              draggable
              onDragStart={() => onDragStart(step.id, phaseKey, phaseIdx)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => onDrop(phaseKey, phaseIdx)}
              onClick={() => setSelectedId(step.id)}
            >
              <span className={styles.stepNum}>{n + 1}</span>
              <span className={styles.grip} title="Drag to reorder (within its phase)">
                ⠿
              </span>
              <div className={styles.stepBody}>
                <div className={styles.stepName}>{step.op}</div>
                <div className={styles.stepMeta}>
                  {step.field ? step.field : "—"}
                  {step.params && Object.keys(step.params).length
                    ? ` · ${Object.keys(step.params).length} param(s)`
                    : ""}
                </div>
              </div>
              <div className={styles.stepActions}>
                <button
                  type="button"
                  className={styles.iconBtn}
                  title={step.enabled ? "Disable step" : "Enable step"}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSteps(toggleStep(steps, step.id));
                  }}
                >
                  {step.enabled ? "◉" : "○"}
                </button>
                <button
                  type="button"
                  className={styles.iconBtn}
                  title="Remove step"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRemove(step.id);
                  }}
                >
                  🗑
                </button>
              </div>
            </div>
          ))}
          <button
            type="button"
            className={styles.addStepBtn}
            onClick={() => setLibraryOpen(true)}
          >
            + Add Step
          </button>
        </div>
      </div>

      {/* ── Right column: selected-step configuration ── */}
      <div className={styles.rightCol}>
      <div className={[styles.pane, styles.paneConfig].join(" ")}>
        <p className={styles.paneTitle}>Step Configuration</p>
        {!selected && <p className={styles.hint}>Select a step to configure.</p>}
        {selected && selectedEntry && (
          <div>
            <div className={styles.field}>
              <Badge variant="warning">{selected.op}</Badge>{" "}
              <span className={styles.hint}>{selectedEntry.description}</span>
            </div>

            {selectedEntry.requires_field && (
              <div className={styles.field}>
                <label className={styles.fieldLabel}>Field</label>
                <select
                  className={styles.select}
                  value={selected.field ?? ""}
                  onChange={(e) => setSteps(updateStep(steps, selected.id, { field: e.target.value || null }))}
                >
                  <option value="">— select column —</option>
                  {sourceColumns.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {[...(selectedEntry.required_params ?? []), ...(selectedEntry.optional_params ?? [])].map(
              (paramName) => (
                <ParamField
                  key={paramName}
                  name={paramName}
                  value={selected.params?.[paramName]}
                  columns={sourceColumns}
                  onChange={setParam}
                />
              ),
            )}

            {(selectedEntry.required_params ?? []).length === 0 &&
              (selectedEntry.optional_params ?? []).length === 0 &&
              !selectedEntry.requires_field && (
                <p className={styles.hint}>This step takes no parameters.</p>
              )}
          </div>
        )}
      </div>
      </div>
    </div>
  );
}
