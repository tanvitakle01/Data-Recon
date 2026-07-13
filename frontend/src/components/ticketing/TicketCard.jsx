import { StatusPill } from "../cockpit/CockpitPrimitives";
import { toneForLevel, scoreToHex } from "../cockpit/cockpitUtils";
import { toneForStatus, formatDate, formatRelativeShort } from "./ticketUiUtils";
import { openTicketCount } from "../../ticketing/assignmentEngine";
import { nextLifecycleAction } from "../../ticketing/lifecycle";
import { isOverdue } from "../../ticketing/slaRules";

/**
 * One ticket card. Purely presentational + action callbacks — no
 * assignment/routing/lifecycle logic lives here: the next-step button comes
 * from `nextLifecycleAction`, and clicking it calls back up to
 * TicketingContext through `onAdvance`.
 */
export default function TicketCard({ ticket, tickets, onOpenDetails, onAssign, onReassign, onAdvance }) {
  const workload = ticket.assignee ? openTicketCount(ticket.assignee.id, tickets) : null;
  const confidenceTone = scoreToHex(ticket.confidence);
  const lastActivity = ticket.activity[ticket.activity.length - 1];
  const nextAction = nextLifecycleAction(ticket.status);
  const overdue = isOverdue(ticket);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_4px_16px_rgba(2,6,23,0.04)] transition-shadow hover:shadow-[0_10px_28px_rgba(2,6,23,0.08)]">
      <div className="mb-3 flex items-start justify-between gap-3">
        <button type="button" onClick={() => onOpenDetails(ticket)} className="text-left">
          <div className="flex items-center gap-1.5 text-[11px] font-black uppercase tracking-widest text-slate-400">
            {ticket.id}
            {ticket.occurrences > 1 ? (
              <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-extrabold text-slate-500">×{ticket.occurrences}</span>
            ) : null}
          </div>
          <div className="text-sm font-extrabold text-slate-900 hover:text-blue-600">{ticket.title}</div>
        </button>
        <div className="flex flex-col items-end gap-1">
          <StatusPill tone={toneForStatus(ticket.status)}>{ticket.status}</StatusPill>
          {overdue ? <StatusPill tone="danger">Overdue</StatusPill> : null}
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <StatusPill tone={toneForLevel(ticket.priority)}>{ticket.priority} Priority</StatusPill>
        <StatusPill tone={toneForLevel(ticket.complexity)}>{ticket.complexity} Complexity</StatusPill>
        <span className="text-xs font-bold tabular-nums" style={{ color: confidenceTone }}>
          Confidence: {ticket.confidence}%
        </span>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 rounded-xl bg-slate-50 p-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Team</div>
          <div className="truncate text-xs font-extrabold text-slate-800">{ticket.team?.name || "Unrouted"}</div>
        </div>
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Assignee</div>
          {ticket.assignee ? (
            <div className="truncate text-xs font-extrabold text-slate-800">
              {ticket.assignee.name}
              <span className="ml-1.5 font-semibold text-slate-400">({workload} open)</span>
            </div>
          ) : (
            <div className="text-xs font-bold text-slate-400">Unassigned</div>
          )}
        </div>
      </div>

      <div className="mb-3 text-[10px] font-bold uppercase tracking-wide text-slate-400">
        Last Updated: <span className="text-slate-500 normal-case">{lastActivity ? formatRelativeShort(lastActivity.ts) : formatDate(ticket.createdAt)}</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {!ticket.assignee ? (
          <button
            type="button"
            onClick={() => onAssign(ticket)}
            className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-extrabold text-blue-700 hover:bg-blue-100"
          >
            Assign
          </button>
        ) : (
          <button
            type="button"
            onClick={() => onReassign(ticket)}
            className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-extrabold text-slate-600 hover:border-slate-300 hover:bg-slate-50"
          >
            Reassign
          </button>
        )}
        {nextAction ? (
          <button
            type="button"
            onClick={() => onAdvance(ticket, nextAction.action)}
            className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-extrabold text-emerald-700 hover:bg-emerald-100"
          >
            {nextAction.label}
          </button>
        ) : null}
      </div>
    </div>
  );
}
