// Pure model for the step-recipe editor. A recipe is an ordered, named list of
// steps — each step IS one ContractOperation. This module is the single source
// of truth for how steps map to the `operations` array the deterministic
// executor runs, and for the Decision-B ordering rule:
//
//   The executor applies operations in FIXED PHASES — Filters → Transforms →
//   Aggregations — preserving each op's relative order WITHIN its phase. A
//   step's phase is therefore fixed by its op KIND; it can only be reordered
//   among steps of the same phase. Serialising concatenates the phases in that
//   fixed order, so the order the user SEES (grouped by phase) is exactly the
//   order the executor RUNS. There is no way to author an order the executor
//   would disagree with.
//
// COMPARE ops are excluded from the recipe entirely (the reconciler uses them,
// not the shadow builder).

let _seq = 0;
function nextId() {
  _seq += 1;
  return `step_${Date.now().toString(36)}_${_seq}`;
}

// Fixed phase order — index drives both the palette grouping and serialisation.
export const PHASES = [
  { key: "filter", kind: "filter", label: "Filters", hint: "Drop rows on raw values" },
  { key: "transform", kind: "transform", label: "Transforms", hint: "Reshape values, in order" },
  { key: "aggregate", kind: "aggregate", label: "Aggregations", hint: "Change row shape" },
];

const PHASE_INDEX = PHASES.reduce((acc, p, i) => ({ ...acc, [p.kind]: i }), {});

export function phaseIndexForKind(kind) {
  return kind in PHASE_INDEX ? PHASE_INDEX[kind] : PHASES.length; // unknown -> last
}

// A step is authored from a catalogue entry (name/kind/params schema).
export function makeStep(catalogueEntry) {
  return {
    id: nextId(),
    op: catalogueEntry.name,
    kind: catalogueEntry.kind,
    field: null,
    params: {},
    enabled: true,
  };
}

// Rehydrate steps from an operations array (e.g. Groq-drafted, or a resumed
// draft). Kind is resolved from the catalogue; unknown ops are dropped so the
// editor never shows a step the executor can't run.
export function operationsToSteps(operations, catalogue) {
  const byName = new Map((catalogue ?? []).map((c) => [c.name, c]));
  const steps = [];
  for (const op of operations ?? []) {
    const entry = byName.get(op.op);
    if (!entry || entry.kind === "compare") continue;
    steps.push({
      id: nextId(),
      op: op.op,
      kind: entry.kind,
      field: op.field ?? null,
      params: { ...(op.params ?? {}) },
      enabled: op.enabled !== false,
    });
  }
  return steps;
}

// Steps grouped by phase, preserving each phase's authored order.
export function groupByPhase(steps) {
  const groups = {};
  for (const p of PHASES) groups[p.key] = [];
  for (const step of steps) {
    const key = PHASES[phaseIndexForKind(step.kind)]?.key;
    if (key) groups[key].push(step);
  }
  return groups;
}

// The `operations` array the contract carries. Concatenates phases in fixed
// order, preserving within-phase order — the exact sequence the executor runs.
export function serializeOperations(steps) {
  const ordered = [...steps].sort(
    (a, b) => phaseIndexForKind(a.kind) - phaseIndexForKind(b.kind),
  );
  // Stable sort keeps within-phase order; map to ContractOperation shape.
  return ordered.map((s) => ({
    op: s.op,
    field: s.field ?? null,
    params: s.params ?? {},
    enabled: s.enabled !== false,
  }));
}

// The 0-based index of a step within the fully-serialised operations array —
// used to drive the "preview up to this step" call. Mirrors serializeOperations.
export function serializedIndexOf(steps, stepId) {
  const ordered = [...steps].sort(
    (a, b) => phaseIndexForKind(a.kind) - phaseIndexForKind(b.kind),
  );
  return ordered.findIndex((s) => s.id === stepId);
}

export function addStep(steps, catalogueEntry) {
  return [...steps, makeStep(catalogueEntry)];
}

export function removeStep(steps, stepId) {
  return steps.filter((s) => s.id !== stepId);
}

export function updateStep(steps, stepId, patch) {
  return steps.map((s) => (s.id === stepId ? { ...s, ...patch } : s));
}

export function toggleStep(steps, stepId) {
  return steps.map((s) => (s.id === stepId ? { ...s, enabled: !s.enabled } : s));
}

// Reorder a step within its OWN phase only (Decision B — cross-phase moves are
// disallowed; a drag toward another phase snaps back). `phaseKey` scopes the
// move; `fromIdx`/`toIdx` are indices within that phase's group.
export function reorderWithinPhase(steps, phaseKey, fromIdx, toIdx) {
  const phaseKind = PHASES.find((p) => p.key === phaseKey)?.kind;
  if (phaseKind == null) return steps;

  // Positions (in the flat array) of the steps belonging to this phase.
  const positions = [];
  steps.forEach((s, i) => {
    if (PHASES[phaseIndexForKind(s.kind)]?.key === phaseKey) positions.push(i);
  });
  if (fromIdx < 0 || fromIdx >= positions.length) return steps;
  const clampedTo = Math.max(0, Math.min(toIdx, positions.length - 1));
  if (fromIdx === clampedTo) return steps;

  // Reorder the phase's steps, then splice them back into their positions.
  const phaseSteps = positions.map((p) => steps[p]);
  const [moved] = phaseSteps.splice(fromIdx, 1);
  phaseSteps.splice(clampedTo, 0, moved);

  const next = [...steps];
  positions.forEach((p, i) => {
    next[p] = phaseSteps[i];
  });
  return next;
}
