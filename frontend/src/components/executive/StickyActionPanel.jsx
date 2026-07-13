const PRIORITY_RANK = { High: 3, Medium: 2, Low: 1 };

/**
 * Sticky remediation rail — the top 1-3 actions from `cockpit.actionCenter`
 * stay visible while scrolling the rest of the Executive Summary, so the
 * highest-impact next step is never more than a glance away. Read-only for
 * now: no Jira/ServiceNow/assign-owner buttons since there's no connector
 * to wire them to yet.
 */
export default function StickyActionPanel({ actionCenter }) {
  const actions = Array.isArray(actionCenter) ? actionCenter : [];
  if (!actions.length) return null;

  const top = [...actions]
    .sort((a, b) => (PRIORITY_RANK[b.priority] || 0) - (PRIORITY_RANK[a.priority] || 0))
    .slice(0, 3);

  return (
    <div className="rounded-3xl border border-slate-200 bg-white/90 backdrop-blur-sm p-5 shadow-[0_10px_30px_rgba(2,6,23,0.06)]">
      <div className="mb-4 text-[11px] font-black uppercase tracking-widest text-slate-400">Priority Remediation</div>
      <div className="space-y-4">
        {top.map((action, idx) => (
          <div key={action.title + idx} className={idx > 0 ? "border-t border-slate-100 pt-4" : ""}>
            <div className="mb-1 text-base font-black leading-tight text-emerald-700">{action.expectedImpact}</div>
            <div className="text-xs font-extrabold leading-snug text-slate-900">{action.title}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
