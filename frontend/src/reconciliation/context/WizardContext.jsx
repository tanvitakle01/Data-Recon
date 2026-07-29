import { useEffect, useMemo, useReducer } from "react";
import { WizardContext } from "./wizardContextObject";
import { wizardReducer, createInitialWizardState } from "./wizardReducer";
import { loadWizardDraft, saveWizardDraft } from "./wizardPersistence";

function initWizardState() {
  const draft = loadWizardDraft();
  if (!draft) return createInitialWizardState();
  // Layer the draft over the current initial shape rather than trusting it
  // wholesale: a draft saved before a new top-level slice existed would
  // otherwise rehydrate without it, and the first component to read that slice
  // crashes. The draft still wins for everything it does carry.
  return { ...createInitialWizardState(), ...draft };
}

export function WizardProvider({ children }) {
  const [state, dispatch] = useReducer(wizardReducer, undefined, initWizardState);

  useEffect(() => {
    saveWizardDraft(state);
  }, [state]);

  const value = useMemo(() => ({ state, dispatch }), [state]);

  return <WizardContext.Provider value={value}>{children}</WizardContext.Provider>;
}
