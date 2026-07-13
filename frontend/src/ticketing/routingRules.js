/**
 * Routing rules are user-editable data owned by TicketingContext's store.
 * This file holds the initial seed and a pure lookup (`routeRootCause`) that
 * operates on whatever rules array the caller currently has, so edits made
 * in the Routing Rules editor take effect immediately everywhere routing
 * happens — no UI component branches on root-cause strings itself.
 *
 * Root-cause keys match the taxonomy labels `CockpitAdapter` (backend/ai/
 * insight_adapter.py) already emits in `rootCauseExplorer[].cause`.
 */
export const DEFAULT_ROUTING_RULES = [
  { rootCause: "Product Mapping Gap", teamKey: "masterData", requiredSkill: "Product Mapping" },
  { rootCause: "Location Mapping Gap", teamKey: "masterData", requiredSkill: "Location Mapping" },
  { rootCause: "Master Data Misalignment", teamKey: "masterData", requiredSkill: "" },
  { rootCause: "Missing Transactions", teamKey: "sapIntegration", requiredSkill: "Missing Records" },
  { rootCause: "Date Range Mismatch", teamKey: "sapIntegration", requiredSkill: "SAP Integration" },
  { rootCause: "Quantity Variance", teamKey: "supplyPlanning", requiredSkill: "Quantity Variance" },
];

const DEFAULT_TEAM_KEY = "masterData";

// Display label shown on tickets — the backend's internal taxonomy calls it
// "Missing Transactions", but the ticket-facing wording is "Missing Records"
// per this module's spec. Presentation only, not a routing decision, so it
// stays a static map rather than editable configuration.
const ROOT_CAUSE_DISPLAY_LABEL = {
  "Missing Transactions": "Missing Records",
};

export function routeRootCause(routingRules, rootCause) {
  const rule = (routingRules || []).find((r) => r.rootCause === rootCause);
  return {
    teamKey: rule?.teamKey || DEFAULT_TEAM_KEY,
    requiredSkill: rule?.requiredSkill || null,
  };
}

export function displayLabelForCause(rootCause) {
  return ROOT_CAUSE_DISPLAY_LABEL[rootCause] || rootCause;
}
