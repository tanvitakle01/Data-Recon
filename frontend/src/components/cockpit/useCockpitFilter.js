import { useContext } from "react";
import { CockpitFilterContext } from "./cockpitFilterContextObject";

export function useCockpitFilter() {
  const ctx = useContext(CockpitFilterContext);
  if (!ctx) {
    throw new Error("useCockpitFilter must be used within a CockpitFilterProvider");
  }
  return ctx;
}
