/**
 * Ticket shape, documented as one factory so every producer (real root
 * causes, demo seed data, future real API responses) constructs the same
 * object. This is the contract UI components read against.
 *
 * {
 *   id: "INV-1001",
 *   title: string,
 *   rootCause: string,          // taxonomy label, e.g. "Product Mapping Gap"
 *   confidence: number,         // 0-100
 *   priority: "High"|"Medium"|"Low",
 *   complexity: "High"|"Medium"|"Low",
 *   impactSummary: string,
 *   affectedRecords: number,
 *   occurrences: number,        // how many detections have rolled into this ticket
 *   status: "Open"|"Assigned"|"In Progress"|"Pending Validation"|"Resolved"|"Closed",
 *   team: { key, name } | null,
 *   assignee: { id, name } | null,
 *   createdAt: ISO string,
 *   lastSeenAt: ISO string,     // most recent detection that touched this ticket
 *   sourceId: string,           // reconciliation file_id or demo/seed marker of the *first* detection
 *   lastSourceId: string,       // reconciliation file_id or demo/seed marker of the *latest* detection
 *   evidence: string,
 *   activity: [{ ts: ISO string, message: string }],
 *   notes: [{ ts: ISO string, text: string }],
 * }
 */
export function createTicket({
  id,
  title,
  rootCause,
  confidence,
  priority,
  complexity,
  impactSummary,
  affectedRecords,
  team,
  sourceId,
  evidence,
}) {
  const createdAt = new Date().toISOString();
  return {
    id,
    title,
    rootCause,
    confidence,
    priority,
    complexity,
    impactSummary,
    affectedRecords: Number(affectedRecords) || 0,
    occurrences: 1,
    status: "Open",
    team,
    assignee: null,
    createdAt,
    lastSeenAt: createdAt,
    sourceId,
    lastSourceId: sourceId,
    evidence,
    activity: [{ ts: createdAt, message: `Ticket ${id} created from detected root cause "${rootCause}".` }],
    notes: [],
  };
}
