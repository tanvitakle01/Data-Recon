import { simulateSend } from "./emailProvider";
import { findTeam } from "../teamDirectory";

/**
 * Builds and "sends" the assignment notification for a ticket. Recipients:
 * the assignee, the team's distribution email, and the team's manager if a
 * manager email is on file (this demo only stores a manager *name*, so the
 * manager is CC'd by name-in-body rather than a fabricated email address —
 * swap in a real manager email field here once that data exists).
 */
export async function sendAssignmentNotification(ticket, member, teams) {
  const team = findTeam(teams, ticket.team?.key);
  const to = [member.email].filter(Boolean);
  const cc = [team?.distributionEmail].filter(Boolean);

  const subject = `[${ticket.id}] Investigation Ticket Assigned: ${ticket.title}`;
  const body = [
    `${member.name},`,
    "",
    `You have been assigned investigation ticket ${ticket.id}: "${ticket.title}".`,
    `Root Cause: ${ticket.rootCause} (${ticket.confidence}% confidence)`,
    `Priority: ${ticket.priority} | Complexity: ${ticket.complexity}`,
    `Team: ${team?.name || ticket.team?.name || "Unassigned"}`,
    team?.managerName ? `Manager: ${team.managerName}` : null,
    "",
    `Evidence: ${ticket.evidence || "See ticket for details."}`,
  ]
    .filter((line) => line !== null)
    .join("\n");

  return simulateSend({ to, cc, subject, body });
}
