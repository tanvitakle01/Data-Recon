import { useMemo, useRef, useState } from "react";
import { CockpitFilterContext } from "./cockpitFilterContextObject";

/**
 * Shared drilldown state: any zone can call `drillTo()` to point the
 * Investigation Workspace at a dimension/value (or just a descriptive
 * label when the insight isn't a literal filterable column, e.g. a root
 * cause). `open` lives here (not as an effect-derived state inside the
 * workspace) so drillTo can open the panel directly from the click handler
 * that triggered it, instead of setState-inside-an-effect.
 */
export function CockpitFilterProvider({ children }) {
  const [filter, setFilter] = useState(null);
  const [open, setOpen] = useState(false);
  const workspaceRef = useRef(null);

  const drillTo = (next) => {
    setFilter({ ...next, ts: Date.now() });
    setOpen(true);
    requestAnimationFrame(() => {
      workspaceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  const clearFilter = () => setFilter(null);

  const value = useMemo(
    () => ({ filter, drillTo, clearFilter, open, setOpen, workspaceRef }),
    [filter, open],
  );

  return <CockpitFilterContext.Provider value={value}>{children}</CockpitFilterContext.Provider>;
}
