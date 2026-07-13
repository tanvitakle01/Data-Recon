import { SectionShell } from "../cockpit/CockpitPrimitives";

const PRIORITY_RANK = { High: 3, Medium: 2, Low: 1 };
const PRIORITY_COLOR = { High: "#ef4444", Medium: "#f59e0b", Low: "#94a3b8" };

/**
 * Executive Summary, section 6 — Recommended Actions prioritized by impact.
 * Same `cockpit.actionCenter` data as Detailed Insights' Action Roadmap,
 * flattened into one impact-ranked list instead of priority lanes since the
 * exec view favors "what matters most" over a kanban-style workflow view.
 */
export default function RecommendedActionsCard({ actionCenter }) {
  const actions = Array.isArray(actionCenter) ? actionCenter : [];
  if (!actions.length) return null;

  const sorted = [...actions].sort((a, b) => (PRIORITY_RANK[b.priority] || 0) - (PRIORITY_RANK[a.priority] || 0));

  return (
    <SectionShell eyebrow="What To Do Next" title="Recommended Actions">
      <div className="space-y-3">
        {sorted.map((action, idx) => (
          <div
            key={action.title + idx}
            className="rounded-2xl border border-slate-200 bg-white p-4 border-l-[3px]"
            style={{ borderLeftColor: PRIORITY_COLOR[action.priority] || "#94a3b8" }}
          >
            <div className="mb-1 flex items-center justify-between gap-3">
              <span className="text-sm font-extrabold text-slate-900">{action.title}</span>
              <span className="text-xs font-black text-emerald-700">{action.expectedImpact}</span>
            </div>
            <div className="mb-2 text-xs font-medium leading-relaxed text-slate-500">{action.reason}</div>
            <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[11px] font-extrabold text-slate-600">
              {action.owner}
            </span>
          </div>
        ))}
      </div>
    </SectionShell>
  );
}
