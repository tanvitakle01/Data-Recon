import { useState } from "react";
import { useTicketing } from "../../ticketing/useTicketing";
import TicketKpiHeader from "./TicketKpiHeader";
import TicketQueue from "./TicketQueue";
import AssignmentPanel from "./AssignmentPanel";
import TicketDetailsDrawer from "./TicketDetailsDrawer";

const DEFAULT_FILTERS = { status: "All", priority: "All", teamKey: "All", assignee: "All", rootCause: "All", search: "" };

const LIFECYCLE_ACTIONS = {
  startProgress: "startProgress",
  requestValidation: "requestValidation",
  resolveTicket: "resolveTicket",
  closeTicket: "closeTicket",
};

export default function TicketDashboardTab() {
  const ticketing = useTicketing();
  const { tickets, teams, assignTicket, overrideAssignment, autoAssignTicket, addNote, loadDemoTickets } = ticketing;
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [assignmentTicket, setAssignmentTicket] = useState(null);
  const [detailsTicket, setDetailsTicket] = useState(null);

  const detailsLive = detailsTicket ? tickets.find((t) => t.id === detailsTicket.id) || null : null;

  const onAdvance = (ticket, actionName) => {
    const action = ticketing[LIFECYCLE_ACTIONS[actionName]];
    if (action) action(ticket.id);
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="m-0 text-2xl font-black tracking-tight text-slate-900">Investigation Tickets</h2>
          <div className="mt-1 text-sm font-semibold text-slate-500">
            Reconciliation root causes routed to owning teams for remediation.
          </div>
        </div>
        <button
          type="button"
          onClick={loadDemoTickets}
          className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-extrabold text-slate-600 hover:border-slate-300 hover:bg-slate-50"
        >
          Load Demo Tickets
        </button>
      </div>

      <TicketKpiHeader tickets={tickets} />

      {tickets.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-200 p-12 text-center">
          <div className="mb-2 text-sm font-extrabold text-slate-700">No investigation tickets yet</div>
          <div className="mb-4 text-sm font-medium text-slate-400">
            Tickets are generated automatically from detected root causes after a reconciliation run, or you can load
            a demo set to explore the workflow.
          </div>
          <button
            type="button"
            onClick={loadDemoTickets}
            className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-extrabold text-white"
          >
            Load Demo Tickets
          </button>
        </div>
      ) : (
        <TicketQueue
          tickets={tickets}
          allTickets={tickets}
          teams={teams}
          filters={filters}
          onFilterChange={setFilters}
          onOpenDetails={setDetailsTicket}
          onAssign={setAssignmentTicket}
          onReassign={setAssignmentTicket}
          onAdvance={onAdvance}
        />
      )}

      {assignmentTicket ? (
        <AssignmentPanel
          ticket={assignmentTicket}
          onClose={() => setAssignmentTicket(null)}
          onManualAssign={(teamKey, memberId, isOverride, recommendedName) => {
            if (isOverride) overrideAssignment(assignmentTicket.id, { teamKey, memberId }, recommendedName);
            else assignTicket(assignmentTicket.id, { teamKey, memberId });
          }}
          onAutoAssign={() => autoAssignTicket(assignmentTicket.id)}
        />
      ) : null}

      {detailsLive ? (
        <TicketDetailsDrawer ticket={detailsLive} onClose={() => setDetailsTicket(null)} onAddNote={addNote} />
      ) : null}
    </div>
  );
}
