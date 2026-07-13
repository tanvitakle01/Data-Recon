import { useState } from "react";
import { FiX, FiPlus, FiEdit2, FiTrash2 } from "react-icons/fi";
import { StatusPill } from "../../cockpit/CockpitPrimitives";
import { workloadTier } from "../ticketUiUtils";
import { openTicketCount } from "../../../ticketing/assignmentEngine";
import { membersForTeam } from "../../../ticketing/teamDirectory";
import { useTicketing } from "../../../ticketing/useTicketing";
import MemberFormModal from "./MemberFormModal";

const AVAILABILITY_TONE = { Available: "success", Busy: "warning", "Out of Office": "neutral" };

export default function TeamDetailsDrawer({ team, onClose }) {
  const { members, teams, tickets, addMember, updateMember, removeMember } = useTicketing();
  const [editingMember, setEditingMember] = useState(null);
  const [addingMember, setAddingMember] = useState(false);

  const teamMembers = membersForTeam(members, team.key);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/40" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-lg flex-col overflow-y-auto border-l border-slate-200 bg-white p-6 shadow-2xl animate-[fadeIn_200ms_ease-out]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <div className="text-[11px] font-black uppercase tracking-widest text-slate-400">Team Details</div>
            <h3 className="m-0 text-xl font-extrabold text-slate-900">{team.name}</h3>
            <p className="mt-1 text-sm font-medium text-slate-500">{team.description}</p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600" aria-label="Close">
            <FiX size={20} />
          </button>
        </div>

        <div className="mb-6 grid grid-cols-2 gap-3 rounded-xl bg-slate-50 p-3">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Manager</div>
            <div className="text-xs font-extrabold text-slate-800">{team.managerName || "—"}</div>
          </div>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Distribution Email</div>
            <div className="text-xs font-extrabold text-slate-800">{team.distributionEmail || "—"}</div>
          </div>
        </div>

        <div className="mb-3 flex items-center justify-between">
          <div className="text-[11px] font-black uppercase tracking-wide text-slate-400">Members ({teamMembers.length})</div>
          <button
            type="button"
            onClick={() => setAddingMember(true)}
            className="flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-extrabold text-blue-700 hover:bg-blue-100"
          >
            <FiPlus size={12} /> Add Member
          </button>
        </div>

        <div className="space-y-3">
          {teamMembers.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-200 p-4 text-center text-xs font-semibold text-slate-400">
              No members on this team yet.
            </div>
          ) : (
            teamMembers.map((member) => {
              const openCount = openTicketCount(member.id, tickets);
              const assignedCount = tickets.filter((t) => t.assignee?.id === member.id).length;
              return (
                <div key={member.id} className="rounded-2xl border border-slate-200 bg-white p-4">
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <div>
                      <div className="text-sm font-extrabold text-slate-900">{member.name}</div>
                      <div className="text-xs font-semibold text-slate-400">{member.email}</div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => setEditingMember(member)}
                        className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                        aria-label={`Edit ${member.name}`}
                      >
                        <FiEdit2 size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => removeMember(member.id)}
                        className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-red-50 hover:text-red-600"
                        aria-label={`Remove ${member.name}`}
                      >
                        <FiTrash2 size={13} />
                      </button>
                    </div>
                  </div>

                  <div className="mb-2 flex flex-wrap gap-1.5">
                    {member.skills.map((skill) => (
                      <span key={skill} className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500">
                        {skill}
                      </span>
                    ))}
                  </div>

                  <div className="grid grid-cols-4 gap-2 text-center">
                    <div>
                      <div className="text-sm font-black tabular-nums text-slate-900">{openCount}</div>
                      <div className="text-[9px] font-bold uppercase tracking-wide text-slate-400">Open</div>
                    </div>
                    <div>
                      <div className="text-sm font-black text-slate-900">{workloadTier(openCount)}</div>
                      <div className="text-[9px] font-bold uppercase tracking-wide text-slate-400">Workload</div>
                    </div>
                    <div>
                      <div className="text-sm font-black tabular-nums text-slate-900">{assignedCount}</div>
                      <div className="text-[9px] font-bold uppercase tracking-wide text-slate-400">Assigned</div>
                    </div>
                    <div>
                      <StatusPill tone={AVAILABILITY_TONE[member.availability] || "neutral"}>{member.availability}</StatusPill>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {addingMember ? (
        <MemberFormModal
          teams={teams}
          defaultTeamKey={team.key}
          onClose={() => setAddingMember(false)}
          onSave={(form) => addMember(form)}
        />
      ) : null}

      {editingMember ? (
        <MemberFormModal
          member={editingMember}
          teams={teams}
          onClose={() => setEditingMember(null)}
          onSave={(form) => updateMember(editingMember.id, form)}
        />
      ) : null}
    </div>
  );
}
