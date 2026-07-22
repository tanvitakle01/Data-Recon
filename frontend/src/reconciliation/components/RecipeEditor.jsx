// Step-recipe transformation editor (Fig 4). A visual, structured authoring
// surface over the SAME contract `operations` array the manual flow compiles
// and the deterministic executor runs — no parallel engine. Three panes:
//
//   left   — ordered step list, grouped by execution phase (Filters →
//            Transforms → Aggregations). Drag to reorder WITHIN a phase; a
//            step's phase is fixed by its op kind so cross-phase moves are
//            impossible (Decision B: visible order always == execution order).
//   middle — the selected step's config (field + parameters), driven by the
//            allow-listed registry's param schema.
//   right  — live before/after preview of the recipe (or up to the selected
//            step), via /api/recon/recipe-preview, reusing the shadow diff.
//
// Groq is optional: "Draft steps from a description" (when the parent wires
// onDraftSteps) emits steps into the list that the user then edits. Building
// steps by hand needs no LLM. Both produce the same operations array.
import { useEffect, useMemo, useRef, useState } from "react";
import api from "../../services/api";
import BeforeAfterCurtain from "./BeforeAfterCurtain";
import {
  PHASES,
  addStep,
  groupByPhase,
  operationsToSteps,
  removeStep,
  reorderWithinPhase,
  serializeOperations,
  serializedIndexOf,
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
};

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
  sourceSample = [],
  previewContext = {},
  onDraftSteps,
}) {
  const [catalogue, setCatalogue] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [pulse, setPulse] = useState(false);
  const [draftDesc, setDraftDesc] = useState("");
  const [drafting, setDrafting] = useState(false);
  const dragRef = useRef(null); // { id, phaseKey, index }
  const prevFpRef = useRef(null);
  const timerRef = useRef(null);

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
  const groups = useMemo(() => groupByPhase(steps), [steps]);
  const selected = steps.find((s) => s.id === selectedId) ?? null;
  const selectedEntry = selected ? byName.get(selected.op) : null;

  // ── live preview (debounced) ──────────────────────────────────────────────
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    let cancelled = false;
    timerRef.current = setTimeout(async () => {
      // Clearing inside the (async) debounce callback — not synchronously in the
      // effect body — so an empty recipe drops the preview without a cascading
      // render.
      if (!steps.length || !sourceSample.length) {
        if (!cancelled) setPreview(null);
        return;
      }
      setPreviewLoading(true);
      setPreviewError(null);
      const draft = {
        comparison_type: previewContext.comparison_type ?? "custom",
        source_type: previewContext.source_type ?? "excel",
        target_type: previewContext.target_type ?? "excel",
        operations: serializeOperations(steps),
        source_schema: sourceColumns,
        target_schema: previewContext.target_schema ?? sourceColumns,
      };
      const activeIndex = selectedId ? serializedIndexOf(steps, selectedId) : null;
      try {
        const res = await api.post("/api/recon/recipe-preview", {
          draft,
          source_rows: sourceSample,
          active_step_index: activeIndex >= 0 ? activeIndex : null,
        });
        if (cancelled) return;
        const data = res.data;
        if (prevFpRef.current && prevFpRef.current !== data.shadow_fingerprint) {
          setPulse(true);
          setTimeout(() => setPulse(false), 900);
        }
        prevFpRef.current = data.shadow_fingerprint;
        setPreview(data);
      } catch (err) {
        if (cancelled) return;
        const detail = err?.response?.data?.detail;
        setPreviewError(typeof detail === "string" ? detail : "Could not build the preview.");
        setPreview(null);
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    }, 400);
    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [steps, selectedId, sourceSample, sourceColumns, previewContext]);

  const previewColumns = useMemo(() => {
    if (!preview) return [];
    return Array.from(
      new Set([...(preview.source?.columns ?? []), ...(preview.shadow?.columns ?? [])]),
    );
  }, [preview]);

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
      {/* ── Left column (40%): step list + palette, full height, scrollable ── */}
      <div className={[styles.pane, styles.paneSteps].join(" ")}>
        <p className={styles.paneTitle}>Recipe</p>
        {PHASES.map((phase) => (
          <div key={phase.key} className={styles.phase}>
            <div className={styles.phaseHead}>
              <span className={styles.phaseLabel}>{phase.label}</span>
              <span className={styles.phaseHint}>{phase.hint}</span>
            </div>
            {groups[phase.key].length === 0 && (
              <p className={styles.emptyPhase}>No steps — add one below.</p>
            )}
            {groups[phase.key].map((step, idx) => (
              <div
                key={step.id}
                className={[
                  styles.step,
                  selectedId === step.id ? styles.stepSelected : "",
                  step.enabled ? "" : styles.stepDisabled,
                ].join(" ")}
                draggable
                onDragStart={() => onDragStart(step.id, phase.key, idx)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => onDrop(phase.key, idx)}
                onClick={() => setSelectedId(step.id)}
              >
                <span className={styles.grip} title="Drag to reorder within this phase">
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
            {/* palette for this phase's kind */}
            <div className={styles.palette}>
              {catalogue
                .filter((c) => c.kind === phase.kind)
                .map((entry) => (
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
        ))}

        {onDraftSteps && (
          <div className={styles.field} style={{ marginTop: 12 }}>
            <label className={styles.fieldLabel}>Draft steps from a description (optional AI)</label>
            <input
              className={styles.input}
              value={draftDesc}
              placeholder="e.g. remove leading zeros from Plant, then prefix PL"
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
                {drafting ? "Drafting…" : "Draft steps"}
              </Button>
            </div>
            <p className={styles.hint}>Drafted steps are added below for you to edit — nothing is auto-applied.</p>
          </div>
        )}
      </div>

      {/* ── Right column (60%): config (top) stacked over preview (bottom) ── */}
      <div className={styles.rightCol}>
      {/* Top panel: selected-step configuration */}
      <div className={[styles.pane, styles.paneConfig].join(" ")}>
        <p className={styles.paneTitle}>Step Configuration</p>
        {!selected && <p className={styles.hint}>Select a step to configure it.</p>}
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

      {/* Bottom panel: live preview — largest, always visible */}
      <div className={[styles.pane, styles.panePreview, pulse ? styles.previewPulse : ""].join(" ")}>
        <p className={styles.paneTitle}>
          Live Preview
          {selected ? " (up to selected step)" : ""}
        </p>
        {!sourceSample.length && (
          <p className={styles.hint}>Load source data to preview the recipe.</p>
        )}
        {previewLoading && <p className={styles.hint}>Building preview…</p>}
        {previewError && <p className={styles.exprError}>⚠️ {previewError}</p>}
        {preview && !previewError && (
          <>
            <div className={styles.previewMeta}>
              {preview.shadow?.total_rows ?? 0} shadow rows
              {preview.row_count_changed ? " (row count changed)" : ""} · {preview.changed_cells ?? 0}{" "}
              changed cells
            </div>
            {preview.affected_columns?.length > 0 && (
              <div className={styles.affected}>
                {preview.affected_columns.map((c) => (
                  <Badge key={c} variant="info">
                    {c}
                  </Badge>
                ))}
              </div>
            )}
            <BeforeAfterCurtain columns={previewColumns} diffs={preview.diffs ?? []} />
          </>
        )}
      </div>
      </div>
    </div>
  );
}
