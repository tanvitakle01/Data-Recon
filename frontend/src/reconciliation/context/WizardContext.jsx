import { useMemo, useReducer } from "react";
import { WizardContext } from "./wizardContextObject";
import { wizardReducer, createInitialWizardState } from "./wizardReducer";

// Stage 1 is stateless: wizard state lives only in memory for the current
// browser session. No sessionStorage/localStorage backing — closing the tab
// or refreshing loses everything, which is the intended behavior here.
export function WizardProvider({ children }) {
  const [state, dispatch] = useReducer(wizardReducer, undefined, createInitialWizardState);

  const value = useMemo(() => ({ state, dispatch }), [state]);

  return <WizardContext.Provider value={value}>{children}</WizardContext.Provider>;
}
