// Bumped to v3 when Comparison Type moved to the front of the wizard: a draft
// saved under the old ordering carries a stepStatus/step that no longer matches
// the new flow (e.g. Comparison Type locked while Source is available), which
// would leave the entry step unreachable. Bumping the key discards those stale
// drafts so returning users start cleanly on the new first step.
const STORAGE_KEY = "reconciliation-wizard-draft-v3";

// File objects and full SAP row arrays can't (or shouldn't) go to
// sessionStorage — File doesn't serialize, and IBP row payloads can exceed
// the storage quota. We keep them in the in-memory reducer state (which is
// what actually powers Back/Continue navigation) and strip them from the
// persisted draft. On a hard refresh the datasets/mapping sheet survive as
// metadata; the heavy data would need to be re-fetched/re-uploaded.
function stripRole(role) {
  if (!role) return role;
  const dataset = role.dataset
    ? { ...role.dataset, rows: undefined, file: undefined }
    : null;
  return { ...role, dataset };
}

function toDraft(state) {
  const spec = state.transformationSpec;
  return {
    ...state,
    source: stripRole(state.source),
    target: stripRole(state.target),
    transformationSpec: spec
      ? {
          ...spec,
          mappingSheet: spec.mappingSheet ? { ...spec.mappingSheet, file: undefined } : null,
        }
      : spec,
  };
}

export function loadWizardDraft() {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveWizardDraft(state) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(toDraft(state)));
  } catch {
    // sessionStorage unavailable (private browsing, quota) — draft simply won't persist
  }
}

export function clearWizardDraft() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(STORAGE_KEY);
}
