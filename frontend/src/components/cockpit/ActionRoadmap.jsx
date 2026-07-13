import { SectionShell } from "./CockpitPrimitives";

// Backend only ever emits High/Medium/Low today. Critical is kept in the
// lane order so the layout is ready for it, but a lane with zero actions
// simply doesn't render — no fabricated placeholder card.
const LANE_ORDER = ["Critical", "High", "Medium", "Low"];
const LANE_COLOR = {
  Critical: { bar: "#991b1b", chip: "bg-red-100 text-red-800 border-red-300" },
  High: { bar: "#ef4444", chip: "bg-red-50 text-red-700 border-red-200" },
  Medium: { bar: "#f59e0b", chip: "bg-amber-50 text-amber-700 border-amber-200" },
  Low: { bar: "#94a3b8", chip: "bg-slate-100 text-slate-600 border-slate-200" },
};

// Tailwind needs literal class strings to detect them at build time —
// a template-interpolated `md:grid-cols-${n}` would silently never apply.
const LANE_GRID_CLASS = {
  1: "md:grid-cols-1",
  2: "md:grid-cols-2",
  3: "md:grid-cols-3",
  4: "md:grid-cols-4",
};

/**
 * Section 7 — the strongest section after the hero: an execution roadmap
 * laid out in priority lanes (like a recovery-plan kanban), not a stacked
 * list of recommendation cards. Each card leads with the expected outcome,
 * since that's the number an executive actually needs to weigh the action.
 */
export default function ActionRoadmap({ actionCenter }) {
  const actions = Array.isArray(actionCenter) ? actionCenter : [];
  if (actions.length === 0) return null;

  const lanes = LANE_ORDER.map((priority) => ({
    priority,
    items: actions.filter((a) => a.priority === priority),
  })).filter((lane) => lane.items.length > 0);

  return (
    <SectionShell step="07" eyebrow="What To Do Next · Execution Roadmap" title="Action Command Center">
      <div className={`grid grid-cols-1 gap-4 ${LANE_GRID_CLASS[Math.min(lanes.length, 4)] || ""}`}>
        {lanes.map((lane) => {
          const color = LANE_COLOR[lane.priority];
          return (
            <div key={lane.priority}>
              <div className="flex items-center gap-2 mb-3">
                <span className="h-2 w-2 rounded-full flex-shrink-0" style={{ background: color.bar }} />
                <span className="text-slate-900 font-black text-xs uppercase tracking-wide">{lane.priority}</span>
                <span className="text-slate-300 font-bold text-xs">({lane.items.length})</span>
              </div>

              <div className="space-y-3">
                {lane.items.map((action, idx) => (
                  <div key={action.title + idx} className="rounded-2xl border border-slate-200 bg-white p-4 border-t-[3px]" style={{ borderTopColor: color.bar }}>
                    <div className="text-emerald-700 font-black text-lg leading-tight mb-1">{action.expectedImpact}</div>
                    <div className="text-slate-900 font-extrabold text-sm mb-2">{action.title}</div>
                    <div className="text-slate-500 font-medium text-xs leading-relaxed mb-3">{action.reason}</div>
                    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-extrabold ${color.chip}`}>
                      {action.owner}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </SectionShell>
  );
}
