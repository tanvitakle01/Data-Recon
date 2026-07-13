import { useMemo } from "react";
import TicketCard from "./TicketCard";

const STATUS_OPTIONS = ["All", "Open", "Assigned", "In Progress", "Pending Validation", "Resolved", "Closed"];
const PRIORITY_OPTIONS = ["All", "High", "Medium", "Low"];

export default function TicketQueue({ tickets, allTickets, teams, filters, onFilterChange, ...cardHandlers }) {
  const assigneeOptions = useMemo(() => {
    const names = new Set(tickets.filter((t) => t.assignee).map((t) => t.assignee.name));
    return ["All", ...Array.from(names).sort()];
  }, [tickets]);

  const rootCauseOptions = useMemo(() => {
    const causes = new Set(tickets.map((t) => t.rootCause));
    return ["All", ...Array.from(causes).sort()];
  }, [tickets]);

  const filtered = tickets.filter((t) => {
    if (filters.status !== "All" && t.status !== filters.status) return false;
    if (filters.priority !== "All" && t.priority !== filters.priority) return false;
    if (filters.teamKey !== "All" && t.team?.key !== filters.teamKey) return false;
    if (filters.assignee !== "All" && t.assignee?.name !== filters.assignee) return false;
    if (filters.rootCause !== "All" && t.rootCause !== filters.rootCause) return false;
    if (filters.search) {
      const q = filters.search.toLowerCase();
      const haystack = `${t.id} ${t.rootCause} ${t.assignee?.name || ""}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          type="text"
          value={filters.search}
          onChange={(e) => onFilterChange({ ...filters, search: e.target.value })}
          placeholder="Search ticket ID, root cause, assignee…"
          className="min-w-[220px] flex-1 rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700"
        />
        <select
          value={filters.status}
          onChange={(e) => onFilterChange({ ...filters, status: e.target.value })}
          className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              Status: {s}
            </option>
          ))}
        </select>
        <select
          value={filters.priority}
          onChange={(e) => onFilterChange({ ...filters, priority: e.target.value })}
          className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700"
        >
          {PRIORITY_OPTIONS.map((p) => (
            <option key={p} value={p}>
              Priority: {p}
            </option>
          ))}
        </select>
        <select
          value={filters.teamKey}
          onChange={(e) => onFilterChange({ ...filters, teamKey: e.target.value })}
          className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700"
        >
          <option value="All">Team: All</option>
          {teams.map((team) => (
            <option key={team.key} value={team.key}>
              Team: {team.name}
            </option>
          ))}
        </select>
        <select
          value={filters.assignee}
          onChange={(e) => onFilterChange({ ...filters, assignee: e.target.value })}
          className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700"
        >
          {assigneeOptions.map((name) => (
            <option key={name} value={name}>
              Assignee: {name}
            </option>
          ))}
        </select>
        <select
          value={filters.rootCause}
          onChange={(e) => onFilterChange({ ...filters, rootCause: e.target.value })}
          className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700"
        >
          {rootCauseOptions.map((cause) => (
            <option key={cause} value={cause}>
              Root Cause: {cause}
            </option>
          ))}
        </select>
        <span className="text-xs font-bold text-slate-400">
          {filtered.length} of {tickets.length} tickets
        </span>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-200 p-8 text-center text-sm font-semibold text-slate-400">
          No tickets match these filters.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((ticket) => (
            <TicketCard key={ticket.id} ticket={ticket} tickets={allTickets} {...cardHandlers} />
          ))}
        </div>
      )}
    </div>
  );
}
