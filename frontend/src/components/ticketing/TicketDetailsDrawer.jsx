import { useState } from "react";
import { FiX, FiMail } from "react-icons/fi";
import { StatusPill } from "../cockpit/CockpitPrimitives";
import { toneForLevel } from "../cockpit/cockpitUtils";
import { toneForStatus, formatDate, formatTime } from "./ticketUiUtils";
import { useTicketing } from "../../ticketing/useTicketing";

function evidenceBullets(evidence) {
  if (!evidence) return [];
  return evidence
    .split(/(?<=[.;])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function TicketDetailsDrawer({ ticket, onClose, onAddNote }) {
  const { notifications } = useTicketing();
  const [note, setNote] = useState("");

  const submitNote = () => {
    if (!note.trim()) return;
    onAddNote(ticket.id, note);
    setNote("");
  };

  const ticketNotifications = notifications.filter((n) => n.ticketId === ticket.id);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/40" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-slate-200 bg-white p-6 shadow-2xl animate-[fadeIn_200ms_ease-out]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <div className="text-[11px] font-black uppercase tracking-widest text-slate-400">
              {ticket.id}
              {ticket.occurrences > 1 ? <span className="ml-1.5 text-slate-300">· ×{ticket.occurrences} occurrences</span> : null}
            </div>
            <h3 className="m-0 text-xl font-extrabold text-slate-900">{ticket.title}</h3>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600" aria-label="Close">
            <FiX size={20} />
          </button>
        </div>

        <div className="mb-5 flex flex-wrap gap-2">
          <StatusPill tone={toneForStatus(ticket.status)}>{ticket.status}</StatusPill>
          <StatusPill tone={toneForLevel(ticket.priority)}>{ticket.priority} Priority</StatusPill>
          <StatusPill tone={toneForLevel(ticket.complexity)}>{ticket.complexity} Complexity</StatusPill>
        </div>

        <section className="mb-5">
          <div className="mb-1 text-[11px] font-black uppercase tracking-wide text-slate-400">Root Cause</div>
          <div className="mb-2 text-sm font-extrabold text-slate-900">{ticket.rootCause}</div>
          <div className="text-[11px] font-black uppercase tracking-wide text-slate-400">Confidence</div>
          <div className="text-2xl font-black tabular-nums text-slate-900">{ticket.confidence}%</div>
        </section>

        <section className="mb-5">
          <div className="mb-1 text-[11px] font-black uppercase tracking-wide text-slate-400">Evidence</div>
          <ul className="m-0 list-disc space-y-1 pl-4">
            {evidenceBullets(ticket.evidence).map((line, idx) => (
              <li key={idx} className="text-sm font-medium leading-relaxed text-slate-600">
                {line}
              </li>
            ))}
          </ul>
        </section>

        <section className="mb-5">
          <div className="mb-1 text-[11px] font-black uppercase tracking-wide text-slate-400">Impact</div>
          <p className="m-0 text-sm font-medium leading-relaxed text-slate-600">
            {ticket.affectedRecords} affected records
            {ticket.occurrences > 1 ? ` · last seen ${formatDate(ticket.lastSeenAt)}` : ""}
          </p>
        </section>

        <section className="mb-5 grid grid-cols-2 gap-3 rounded-xl bg-slate-50 p-3">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Assigned Team</div>
            <div className="text-xs font-extrabold text-slate-800">{ticket.team?.name || "Unrouted"}</div>
          </div>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Assigned User</div>
            <div className="text-xs font-extrabold text-slate-800">{ticket.assignee?.name || "Unassigned"}</div>
          </div>
        </section>

        <section className="mb-5">
          <div className="mb-2 text-[11px] font-black uppercase tracking-wide text-slate-400">Activity Timeline</div>
          <div className="space-y-2.5 border-l-2 border-slate-100 pl-3">
            {ticket.activity.map((a, idx) => (
              <div key={idx} className="flex gap-2">
                <span className="w-12 flex-shrink-0 text-[11px] font-black tabular-nums text-slate-400">{formatTime(a.ts)}</span>
                <span className="text-xs font-semibold text-slate-700">{a.message}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="mb-5">
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-black uppercase tracking-wide text-slate-400">
            <FiMail size={12} /> Notifications
          </div>
          {ticketNotifications.length === 0 ? (
            <div className="text-xs font-semibold text-slate-400">No notifications sent yet.</div>
          ) : (
            <div className="space-y-2">
              {ticketNotifications.map((n) => (
                <div key={n.id} className="rounded-xl bg-slate-50 p-2.5">
                  <div className="mb-0.5 flex items-center justify-between">
                    <span className="text-xs font-extrabold text-slate-800">{n.subject}</span>
                    <span className="text-[10px] font-black text-emerald-600">Email Sent ✓</span>
                  </div>
                  <div className="text-[11px] font-semibold text-slate-500">To: {n.to.join(", ")}</div>
                  {n.cc?.length ? <div className="text-[11px] font-semibold text-slate-400">Cc: {n.cc.join(", ")}</div> : null}
                  <div className="mt-1 text-[10px] font-bold text-slate-400">{formatDate(n.sentAt)}</div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section>
          <div className="mb-2 text-[11px] font-black uppercase tracking-wide text-slate-400">Notes</div>
          <div className="mb-3 space-y-2">
            {ticket.notes.length === 0 ? (
              <div className="text-xs font-semibold text-slate-400">No notes yet.</div>
            ) : (
              ticket.notes.map((n, idx) => (
                <div key={idx} className="rounded-xl bg-slate-50 p-2.5">
                  <div className="text-xs font-medium text-slate-700">{n.text}</div>
                  <div className="mt-1 text-[10px] font-bold text-slate-400">{formatDate(n.ts)}</div>
                </div>
              ))
            )}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submitNote()}
              placeholder="Add a note…"
              className="flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-800"
            />
            <button type="button" onClick={submitNote} className="rounded-xl bg-slate-900 px-4 py-2 text-xs font-extrabold text-white">
              Save Note
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
