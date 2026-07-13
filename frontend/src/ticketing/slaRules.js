const ACTIVE_STATUSES = new Set(["Open", "Assigned", "In Progress", "Pending Validation"]);

export const SLA_HOURS_BY_PRIORITY = {
  High: 24,
  Medium: 72,
  Low: 120,
};

export function isOverdue(ticket, now = new Date()) {
  if (!ACTIVE_STATUSES.has(ticket.status)) return false;
  const slaHours = SLA_HOURS_BY_PRIORITY[ticket.priority] ?? SLA_HOURS_BY_PRIORITY.Medium;
  const ageHours = (now.getTime() - new Date(ticket.createdAt).getTime()) / (1000 * 60 * 60);
  return ageHours > slaHours;
}
