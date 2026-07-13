export const LIFECYCLE_STATUSES = ["Open", "Assigned", "In Progress", "Pending Validation", "Resolved", "Closed"];

// Config the UI reads to render exactly one "next step" action per ticket
// card, instead of branching on status strings inline.
const NEXT_ACTION = {
  Assigned: { label: "Start Progress", action: "startProgress" },
  "In Progress": { label: "Request Validation", action: "requestValidation" },
  "Pending Validation": { label: "Resolve", action: "resolveTicket" },
  Resolved: { label: "Close", action: "closeTicket" },
};

export function nextLifecycleAction(status) {
  return NEXT_ACTION[status] || null;
}
