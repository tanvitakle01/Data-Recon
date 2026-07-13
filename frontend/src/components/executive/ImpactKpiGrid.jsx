import { SectionShell, StatusPill } from "../cockpit/CockpitPrimitives";
import { toneForLevel } from "../cockpit/cockpitUtils";

/**
 * Executive Summary, section 3 — Financial / Operational Impact as premium
 * KPI cards, one per business risk lens from `cockpit.businessImpact`
 * (already computed and used by Detailed Insights' Risk Exposure Board).
 */
export default function ImpactKpiGrid({ businessImpact }) {
  const impacts = Array.isArray(businessImpact) ? businessImpact : [];
  if (!impacts.length) return null;

  return (
    <SectionShell eyebrow="Financial / Operational Impact" title="Business Impact">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {impacts.map((impact) => (
          <div key={impact.riskArea} className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-sm font-extrabold text-slate-900">{impact.riskArea}</span>
              <StatusPill tone={toneForLevel(impact.level)}>{impact.level}</StatusPill>
            </div>
            <div className="mb-1.5 text-2xl font-black tabular-nums text-slate-900">{impact.affectedRecords}</div>
            <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-slate-400">Affected Records</div>
            <p className="m-0 text-xs font-medium leading-relaxed text-slate-500">{impact.recommendation}</p>
          </div>
        ))}
      </div>
    </SectionShell>
  );
}
