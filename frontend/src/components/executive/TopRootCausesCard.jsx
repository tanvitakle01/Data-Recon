import { SectionShell, StatusPill } from "../cockpit/CockpitPrimitives";
import { toneForLevel, scoreToHex } from "../cockpit/cockpitUtils";

/**
 * Executive Summary, section 4 — Top 3 Root Causes, confidence-ranked. Same
 * `cockpit.rootCauseExplorer` data as the Detailed Insights Root Cause
 * Board, just the top three surfaced up-front with evidence always visible
 * (no click-to-expand) since this view is meant to be read once, not explored.
 */
export default function TopRootCausesCard({ rootCauseExplorer }) {
  const causes = Array.isArray(rootCauseExplorer) ? rootCauseExplorer.slice(0, 3) : [];
  if (!causes.length) return null;

  return (
    <SectionShell eyebrow="Why It Happened" title="Top 3 Root Causes">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {causes.map((cause, idx) => {
          const tone = scoreToHex(cause.confidence);
          return (
            <div key={cause.cause + idx} className="flex flex-col rounded-2xl border border-slate-200 bg-white p-4">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-sm font-extrabold text-slate-900">{cause.cause}</span>
                <StatusPill tone={toneForLevel(cause.impact)}>{cause.impact}</StatusPill>
              </div>
              <div className="mb-1 text-3xl font-black tabular-nums" style={{ color: tone }}>
                {cause.confidence}%
              </div>
              <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-slate-400">Confidence</div>
              {cause.evidence ? (
                <p className="mb-1 mt-1 text-xs font-semibold leading-relaxed text-slate-600">{cause.evidence}</p>
              ) : null}
              {cause.reasoning ? (
                <p className="m-0 text-[11px] font-medium leading-relaxed text-slate-400">{cause.reasoning}</p>
              ) : null}
              <div className="mt-auto pt-3 text-[11px] font-bold text-slate-400">{cause.affectedRecords} records affected</div>
            </div>
          );
        })}
      </div>
    </SectionShell>
  );
}
