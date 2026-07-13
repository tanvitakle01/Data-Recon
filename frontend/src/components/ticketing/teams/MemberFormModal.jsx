import { useState } from "react";
import { FiX } from "react-icons/fi";
import { AVAILABLE_SKILLS, AVAILABILITY_OPTIONS } from "../../../ticketing/teamDirectory";

function emptyForm(defaultTeamKey) {
  return { name: "", email: "", role: "", teamKey: defaultTeamKey || "", skills: [], availability: "Available" };
}

export default function MemberFormModal({ member, teams, defaultTeamKey, onClose, onSave }) {
  const [form, setForm] = useState(member ? { ...member } : emptyForm(defaultTeamKey));
  const isEdit = Boolean(member);

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const toggleSkill = (skill) => {
    setForm((f) => ({
      ...f,
      skills: f.skills.includes(skill) ? f.skills.filter((s) => s !== skill) : [...f.skills, skill],
    }));
  };

  const submit = () => {
    if (!form.name.trim() || !form.teamKey) return;
    onSave(form);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="m-0 text-lg font-extrabold text-slate-900">{isEdit ? "Edit Member" : "Add Member"}</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600" aria-label="Close">
            <FiX size={18} />
          </button>
        </div>

        <div className="max-h-[65vh] space-y-4 overflow-y-auto pr-1">
          <div>
            <label className="mb-1.5 block text-xs font-bold text-slate-500">Full Name</label>
            <input
              type="text"
              value={form.name}
              onChange={set("name")}
              placeholder="John Doe"
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-800"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-bold text-slate-500">Email Address</label>
            <input
              type="email"
              value={form.email}
              onChange={set("email")}
              placeholder="john@company.com"
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-800"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-bold text-slate-500">Role</label>
            <input
              type="text"
              value={form.role}
              onChange={set("role")}
              placeholder="Data Analyst"
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-800"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-bold text-slate-500">Primary Team</label>
            <select
              value={form.teamKey}
              onChange={set("teamKey")}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-800"
            >
              <option value="" disabled>
                Select a team…
              </option>
              {teams.map((team) => (
                <option key={team.key} value={team.key}>
                  {team.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-bold text-slate-500">Skills</label>
            <div className="flex flex-wrap gap-2">
              {AVAILABLE_SKILLS.map((skill) => (
                <button
                  key={skill}
                  type="button"
                  onClick={() => toggleSkill(skill)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-bold transition-colors ${
                    form.skills.includes(skill) ? "border-blue-300 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-500 hover:bg-slate-50"
                  }`}
                >
                  {skill}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-bold text-slate-500">Availability Status</label>
            <select
              value={form.availability}
              onChange={set("availability")}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-800"
            >
              {AVAILABILITY_OPTIONS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>
        </div>

        <button
          type="button"
          disabled={!form.name.trim() || !form.teamKey}
          onClick={submit}
          className="mt-4 w-full rounded-xl bg-slate-900 py-2.5 text-sm font-extrabold text-white disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
        >
          {isEdit ? "Save Changes" : "Add Member"}
        </button>
      </div>
    </div>
  );
}
