import { useEffect, useMemo, useReducer } from "react";
import { WizardContext } from "./wizardContextObject";
import { wizardReducer, createInitialWizardState } from "./wizardReducer";
import { loadWizardDraft, saveWizardDraft } from "./wizardPersistence";

function initWizardState() {
  const draft = loadWizardDraft();
  return draft ?? createInitialWizardState();
}

export function WizardProvider({ children }) {
  const [state, dispatch] = useReducer(wizardReducer, undefined, initWizardState);

  useEffect(() => {
    saveWizardDraft(state);
  }, [state]);

  const value = useMemo(() => ({ state, dispatch }), [state]);

  return <WizardContext.Provider value={value}>{children}</WizardContext.Provider>;
}
