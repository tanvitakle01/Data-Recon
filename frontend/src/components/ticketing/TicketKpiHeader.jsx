import { isOverdue } from "../../ticketing/slaRules";

const CARD_TONE = {
  slate: "text-slate-900",
  blue: "text-blue-600",
  indigo: "text-indigo-600",
  emerald: "text-emerald-600",
  amber: "text-amber-600",
  red: "text-red-600",
};

const CLOSED_STATUSES = new Set(["Resolved", "Closed"]);

function KpiCard({ label, value, tone = "slate" }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`text-3xl font-black tabular-nums ${CARD_TONE[tone]}`}>{value}</div>
    </div>
  );
}

export default function TicketKpiHeader({ tickets }) {
  const total = tickets.length;
  const open = tickets.filter((t) => t.status === "Open").length;
  const assigned = tickets.filter((t) => t.status === "Assigned").length;
  const inProgress = tickets.filter((t) => t.status === "In Progress").length;
  const critical = tickets.filter((t) => t.priority === "High" && !CLOSED_STATUSES.has(t.status)).length;
  const overdue = tickets.filter((t) => isOverdue(t)).length;

  return (
    <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <KpiCard label="Total Tickets" value={total} tone="slate" />
      <KpiCard label="Open" value={open} tone="blue" />
      <KpiCard label="Assigned" value={assigned} tone="indigo" />
      <KpiCard label="In Progress" value={inProgress} tone="emerald" />
      <KpiCard label="Critical" value={critical} tone="red" />
      <KpiCard label="Overdue" value={overdue} tone="amber" />
    </div>
  );
}
