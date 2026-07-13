import { useState } from "react";
import { FiX } from "react-icons/fi";

const EMPTY = { name: "", description: "", managerName: "", distributionEmail: "" };

export default function TeamFormModal({ team, onClose, onSave }) {
  const [form, setForm] = useState(team ? { ...team } : EMPTY);
  const isEdit = Boolean(team);

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const submit = () => {
    if (!form.name.trim()) return;
    onSave(form);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="m-0 text-lg font-extrabold text-slate-900">{isEdit ? "Edit Team" : "Create Team"}</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600" aria-label="Close">
            <FiX size={18} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-bold text-slate-500">Team Name</label>
            <input
              type="text"
              value={form.name}
              onChange={set("name")}
              placeholder="Master Data Team"
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-800"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-bold text-slate-500">Description</label>
            <textarea
              value={form.description}
              onChange={set("description")}
              placeholder="Handles product and location mapping issues"
              rows={2}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-800"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-bold text-slate-500">Manager Name</label>
            <input
              type="text"
              value={form.managerName}
              onChange={set("managerName")}
              placeholder="Sarah Johnson"
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-800"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-bold text-slate-500">Team Distribution Email</label>
            <input
              type="email"
              value={form.distributionEmail}
              onChange={set("distributionEmail")}
              placeholder="masterdata@company.com"
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-800"
            />
          </div>

          <button
            type="button"
            disabled={!form.name.trim()}
            onClick={submit}
            className="w-full rounded-xl bg-slate-900 py-2.5 text-sm font-extrabold text-white disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
          >
            {isEdit ? "Save Changes" : "Create Team"}
          </button>
        </div>
      </div>
    </div>
  );
}
