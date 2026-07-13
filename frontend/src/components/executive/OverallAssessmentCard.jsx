import ScoreGauge from "../cockpit/ScoreGauge";
import { SectionShell, WhyPanel, ContributorBar } from "../cockpit/CockpitPrimitives";
import { scoreToHex } from "../cockpit/cockpitUtils";

function GaugeBlock({ label, value, tone }) {
  return (
    <div className="flex flex-col items-center">
      <ScoreGauge value={value} tone={tone} size={140} strokeWidth={10}>
        <span className="text-slate-900 font-extrabold text-3xl tabular-nums">{Math.round(value)}</span>
        <span className="text-slate-400 font-extrabold text-[10px] uppercase tracking-wide">{label}</span>
      </ScoreGauge>
    </div>
  );
}

/**
 * Executive Summary, section 1 — Overall Assessment. The Recon Score gauge and
 * its breakdown, reusing the exact gauge/WhyPanel/ContributorBar primitives so
 * the two tabs can never show conflicting math for the same payload.
 */
export default function OverallAssessmentCard({ situationRoom }) {
  if (!situationRoom) return null;

  const { reconciliationScore = 0, reconciliationScoreBreakdown } = situationRoom;
  const contributors = Array.isArray(reconciliationScoreBreakdown?.contributors) ? reconciliationScoreBreakdown.contributors : [];

  return (
    <SectionShell eyebrow="Data → Insights" title="Overall Assessment">
      <div className="flex justify-center mb-6">
        <GaugeBlock label="Recon Score" value={reconciliationScore} tone={scoreToHex(reconciliationScore)} />
      </div>

      {contributors.length ? (
        <div className="border-t border-slate-100 pt-5">
          <WhyPanel label="Why this Recon Score?" openLabel="Hide breakdown">
            <div className="text-slate-400 font-black text-[10px] uppercase tracking-wide mb-2">Derived From:</div>
            <div className="divide-y divide-slate-100">
              {contributors.map((c) => (
                <ContributorBar
                  key={c.name}
                  name={c.name}
                  count={c.count}
                  sharePct={c.sharePct}
                  contributionPct={c.contributionPct}
                  penaltyPoints={c.penaltyPoints}
                  impact={c.impact}
                />
              ))}
            </div>
          </WhyPanel>
        </div>
      ) : null}
    </SectionShell>
  );
}
