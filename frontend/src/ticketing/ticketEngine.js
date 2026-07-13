import { createTicket } from "./ticketModel";
import { routeRootCause, displayLabelForCause } from "./routingRules";
import { findTeam } from "./teamDirectory";

const CLOSED_STATUSES = new Set(["Resolved", "Closed"]);

function complexityFromConfidence(confidence) {
  if (confidence >= 85) return "High";
  if (confidence >= 65) return "Medium";
  return "Low";
}

function priorityForCause(cause) {
  if (cause.impact === "High" || cause.impact === "Medium") return cause.impact;
  return cause.confidence >= 80 ? "High" : "Medium";
}

function nextId(seq) {
  return `INV-${seq}`;
}

function withActivity(ticket, message) {
  return { ...ticket, activity: [...ticket.activity, { ts: new Date().toISOString(), message }] };
}

/**
 * Turns real detected root causes (`cockpit.rootCauseExplorer`) into
 * tickets, reconciled against whatever tickets already exist — across
 * *any* prior reconciliation run, not just the current one. A root cause
 * that already has an active ticket (status not Resolved/Closed) gets that
 * ticket updated in place (occurrence count, latest affected-record count,
 * refreshed confidence, one activity line recording the delta) instead of
 * spawning a duplicate. Only root causes with no active ticket produce a
 * brand new one. Returns the full merged tickets array plus the advanced
 * id sequence, so the caller can replace its tickets state wholesale.
 */
export function reconcileTicketsWithRootCauses(rootCauses, { sourceId, existingTickets = [], routingRules = [], teams = [], nextSeq = 1001 }) {
  const now = new Date().toISOString();
  let seq = nextSeq;
  let tickets = [...existingTickets];

  for (const cause of rootCauses || []) {
    const activeIdx = tickets.findIndex((t) => t.rootCause === cause.cause && !CLOSED_STATUSES.has(t.status));

    if (activeIdx >= 0 && tickets[activeIdx].lastSourceId === sourceId) {
      // Same detection instance already ingested (e.g. revisiting the same
      // reconciliation run's Insights page) — idempotent no-op, not a new
      // occurrence.
      continue;
    }

    if (activeIdx >= 0) {
      const existing = tickets[activeIdx];
      const prevOccurrences = existing.occurrences;
      const prevAffected = existing.affectedRecords;
      const nextOccurrences = prevOccurrences + 1;
      const nextAffected = Number(cause.affectedRecords) || prevAffected;

      tickets[activeIdx] = withActivity(
        {
          ...existing,
          occurrences: nextOccurrences,
          affectedRecords: nextAffected,
          confidence: cause.confidence,
          evidence: cause.evidence || existing.evidence,
          lastSeenAt: now,
          lastSourceId: sourceId,
        },
        `Occurrence detected again: occurrences ${prevOccurrences}→${nextOccurrences}, affected records ${prevAffected}→${nextAffected}.`
      );
      continue;
    }

    const { teamKey } = routeRootCause(routingRules, cause.cause);
    const id = nextId(seq);
    seq += 1;
    tickets.push(
      createTicket({
        id,
        title: `${displayLabelForCause(cause.cause)} Investigation`,
        rootCause: cause.cause,
        confidence: cause.confidence,
        priority: priorityForCause(cause),
        complexity: complexityFromConfidence(cause.confidence),
        impactSummary: cause.evidence || `${cause.affectedRecords ?? 0} records affected.`,
        affectedRecords: cause.affectedRecords,
        team: findTeam(teams, teamKey) || { key: teamKey, name: teamKey },
        sourceId,
        evidence: cause.evidence,
      })
    );
  }

  return { tickets, nextSeq: seq };
}

/**
 * Canned ticket set mirroring the module spec's own worked example, for
 * demoing the Ticketing dashboard standalone (no reconciliation run needed).
 * Goes through the same reconcile path as real detections, so repeated
 * clicks update occurrences instead of duplicating.
 */
export function seedDemoTickets({ existingTickets = [], routingRules = [], teams = [], nextSeq = 1001 } = {}) {
  const demoCauses = [
    {
      cause: "Product Mapping Gap",
      confidence: 87,
      impact: "High",
      affectedRecords: 4,
      evidence: "4 source materials have no target equivalent; missing mappings detected across 3 locations.",
    },
    {
      cause: "Location Mapping Gap",
      confidence: 74,
      impact: "Medium",
      affectedRecords: 6,
      evidence: "6 source plant codes have no corresponding target location mapping.",
    },
    {
      cause: "Quantity Variance",
      confidence: 68,
      impact: "Medium",
      affectedRecords: 9,
      evidence: "9 records show quantity mismatches exceeding the tolerance threshold between source and target.",
    },
    {
      cause: "Missing Transactions",
      confidence: 92,
      impact: "High",
      affectedRecords: 12,
      evidence: "12 source records have no matching target record.",
    },
  ];

  return reconcileTicketsWithRootCauses(demoCauses, { sourceId: "demo-seed", existingTickets, routingRules, teams, nextSeq });
}
