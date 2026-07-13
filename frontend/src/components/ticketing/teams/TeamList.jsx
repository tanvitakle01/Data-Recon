import { FiPlus, FiEdit2, FiTrash2, FiEye } from "react-icons/fi";
import { membersForTeam } from "../../../ticketing/teamDirectory";

export default function TeamList({ teams, members, onCreate, onEdit, onDelete, onViewDetails }) {
  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="m-0 text-2xl font-black tracking-tight text-slate-900">Teams &amp; Members</h2>
          <div className="mt-1 text-sm font-semibold text-slate-500">Own, staff, and route investigation work across teams.</div>
        </div>
        <button
          type="button"
          onClick={onCreate}
          className="flex items-center gap-1.5 rounded-xl bg-slate-900 px-4 py-2 text-sm font-extrabold text-white"
        >
          <FiPlus size={14} /> Create Team
        </button>
      </div>

      {teams.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-200 p-12 text-center text-sm font-semibold text-slate-400">
          No teams yet. Create one to start routing investigation tickets.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {teams.map((team) => {
            const count = membersForTeam(members, team.key).length;
            return (
              <div key={team.key} className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <h3 className="m-0 text-base font-extrabold text-slate-900">{team.name}</h3>
                  <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-extrabold text-slate-600">
                    {count} member{count === 1 ? "" : "s"}
                  </span>
                </div>
                <p className="mb-4 flex-1 text-sm font-medium leading-relaxed text-slate-500">{team.description || "No description."}</p>
                <div className="mb-4 grid grid-cols-1 gap-2 rounded-xl bg-slate-50 p-3">
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Manager</div>
                    <div className="text-xs font-extrabold text-slate-800">{team.managerName || "—"}</div>
                  </div>
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Distribution Email</div>
                    <div className="truncate text-xs font-extrabold text-slate-800">{team.distributionEmail || "—"}</div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => onViewDetails(team)}
                    className="flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-extrabold text-blue-700 hover:bg-blue-100"
                  >
                    <FiEye size={12} /> View Details
                  </button>
                  <button
                    type="button"
                    onClick={() => onEdit(team)}
                    className="flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-extrabold text-slate-600 hover:bg-slate-50"
                  >
                    <FiEdit2 size={12} /> Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(team)}
                    className="flex items-center gap-1 rounded-full border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-extrabold text-red-600 hover:bg-red-100"
                  >
                    <FiTrash2 size={12} /> Delete
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
