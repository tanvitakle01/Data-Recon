import { membersForTeam } from "./teamDirectory";
import { routeRootCause } from "./routingRules";

const AVAILABILITY_RANK = { Available: 2, Busy: 1, "Out of Office": 0 };

export function openTicketCount(memberId, tickets) {
  return tickets.filter((t) => t.assignee?.id === memberId && !["Resolved", "Closed"].includes(t.status)).length;
}

/**
 * Skill Match -> Current Workload -> Availability, in that order, among
 * members of the routed team (team match is a precondition, not a scoring
 * factor). "Out of Office" members are excluded from auto-recommendation
 * entirely — they remain manually selectable in the Assignment Panel as an
 * explicit override, since a human may still want to queue work for them.
 * Workload is computed live from `tickets`, not a static counter, so
 * assigning tickets during the demo actually changes future recommendations.
 * Pure function — no ticket mutation happens here.
 */
export function recommendAssignee(rootCause, tickets, { members, routingRules }) {
  const { teamKey, requiredSkill } = routeRootCause(routingRules, rootCause);
  const candidates = membersForTeam(members, teamKey).filter((m) => m.availability !== "Out of Office");
  if (candidates.length === 0) return null;

  const scored = candidates.map((member) => {
    const skillMatch = Boolean(requiredSkill) && member.skills.includes(requiredSkill);
    const workload = openTicketCount(member.id, tickets);
    const availabilityRank = AVAILABILITY_RANK[member.availability] ?? 0;
    return { member, skillMatch, workload, availabilityRank };
  });

  scored.sort((a, b) => {
    if (a.skillMatch !== b.skillMatch) return a.skillMatch ? -1 : 1;
    if (a.workload !== b.workload) return a.workload - b.workload;
    return b.availabilityRank - a.availabilityRank;
  });

  const best = scored[0];
  const reasons = [];
  if (best.skillMatch) reasons.push(`✓ ${best.member.specialty}`);
  reasons.push(scored.every((s) => s.workload >= best.workload) ? "✓ Lowest Workload" : "✓ Balanced Workload");
  reasons.push(`✓ ${best.workload} Open Ticket${best.workload === 1 ? "" : "s"}`);
  if (best.member.availability === "Available") reasons.push("✓ Currently Available");

  return { teamKey, member: best.member, reasons };
}
