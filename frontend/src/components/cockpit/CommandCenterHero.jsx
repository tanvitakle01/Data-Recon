import { useState } from "react";
import { FiRadio } from "react-icons/fi";
import Counter from "../Counter";
import ScoreGauge from "./ScoreGauge";
import { CopyButton, InfoTooltip, WhyPanel, ContributorBar, StatusPill } from "./CockpitPrimitives";
import { scoreToHex, toneForLevel, toneForHealth, toneToHex } from "./cockpitUtils";

const SEVERITY_HELP = "Severity reflects overall reconciliation accuracy and exception volume: Low when accuracy is 95%+ with 50 or fewer exceptions, Medium at 90%+ accuracy, High otherwise.";
const HEALTH_HELP = "System Health combines Severity and the underlying Risk category: any High/Critical signal marks the system Degraded, Medium marks it Attention Needed, otherwise Healthy.";

function IndicatorLight({ label, value, color, tooltip }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="relative flex h-2.5 w-2.5 flex-shrink-0">
        <span className="absolute inline-flex h-full w-full rounded-full opacity-40 animate-ping" style={{ background: color }} />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      </span>
      <div>
        <div className="flex items-center gap-1 text-slate-400 font-bold text-[10px] uppercase tracking-wide leading-none">
          {label}
          {tooltip ? <InfoTooltip text={tooltip} /> : null}
        </div>
        <div className="text-slate-900 font-extrabold text-sm leading-tight">{value}</div>
      </div>
    </div>
  );
}

function firstSentence(text) {
  if (!text) return "";
  const idx = text.indexOf(". ");
  return idx === -1 ? text : text.slice(0, idx + 1);
}

/**
 * Section 1 — the entire top fold. One focal instrument (Reconciliation
 * Score) instead of a KPI row; three indicator lights instead of status
 * pills; one sentence of briefing with the full narrative one click away.
 * This is the whole "can I trust this, and is it healthy" answer, readable
 * in five seconds without scrolling or reading a paragraph.
 */
export default function CommandCenterHero({ situationRoom, executiveBrief }) {
  const [expanded, setExpanded] = useState(false);
  if (!situationRoom) return null;

  const {
    reconciliationScore = 0,
    reconciliationScoreBreakdown,
    totalExceptions = 0,
    severity = "Low",
    systemHealth = "Healthy",
    confidence,
    narrative,
    readiness,
  } = situationRoom;

  const scoreTone = scoreToHex(reconciliationScore);
  const readinessScore = Number(readiness?.score ?? 100);
  const brief = firstSentence(narrative);
  const hasMore = narrative && narrative.length > brief.length;

  const confidenceScore = Number(confidence?.score ?? readinessScore);
  const confidenceTone = scoreToHex(confidenceScore);
  const confidenceDrivers = Array.isArray(confidence?.drivers) ? confidence.drivers : [];
  const contributors = Array.isArray(reconciliationScoreBreakdown?.contributors) ? reconciliationScoreBreakdown.contributors : [];

  return (
    <section className="cockpit-hero" aria-label="Command Center">
      <div className="flex items-center justify-between gap-3 mb-6">
        <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-[11px] font-black uppercase tracking-widest text-slate-500">
          <FiRadio className="text-emerald-500" size={12} />
          Command Center · Live
        </div>
        <div className="text-slate-400 font-bold text-xs tabular-nums">
          <Counter value={totalExceptions} fontSize={12} fontWeight={800} textColor="#94a3b8" gap={0} /> exceptions tracked
        </div>
      </div>

      <div className="flex flex-col lg:flex-row items-center gap-10">
        {/* Focal instrument: the trust question that matters before anything else */}
        <div className="flex flex-shrink-0 items-center gap-6 md:gap-10">
          <div className="flex flex-col items-center">
            <ScoreGauge value={reconciliationScore} tone={scoreTone} size={168} strokeWidth={12}>
              <Counter value={reconciliationScore} fontSize={44} fontWeight={800} textColor="#0F172A" />
              <span className="text-slate-400 font-extrabold text-[10px] uppercase tracking-wide">Recon Score</span>
            </ScoreGauge>
          </div>
        </div>

        {/* Status + briefing */}
        <div className="flex-1 min-w-0 w-full">
          <div className="grid grid-cols-3 gap-4 mb-5 pb-5 border-b border-slate-100">
            <IndicatorLight label="Severity" value={severity} color={toneToHex(toneForLevel(severity))} tooltip={SEVERITY_HELP} />
            <IndicatorLight label="System Health" value={systemHealth} color={toneToHex(toneForHealth(systemHealth))} tooltip={HEALTH_HELP} />
            <IndicatorLight label="Confidence" value={`${confidenceScore}%`} color={confidenceTone} />
          </div>

          <div>
            <div className="text-slate-400 font-black text-[10px] uppercase tracking-[0.15em] mb-1.5">Briefing</div>
            <p className="text-slate-900 font-bold text-lg leading-snug m-0">{brief || "Reconciliation complete — no exceptions detected."}</p>
            {expanded && hasMore ? <p className="mt-2 text-slate-500 font-medium text-sm leading-relaxed">{narrative.slice(brief.length).trim()}</p> : null}
            <div className="mt-3 flex items-center gap-3">
              {hasMore ? (
                <button type="button" onClick={() => setExpanded((v) => !v)} className="text-blue-600 font-extrabold text-xs hover:text-blue-700">
                  {expanded ? "Show less" : "Read full briefing"}
                </button>
              ) : null}
              {executiveBrief ? <CopyButton text={executiveBrief} label="Copy Executive Brief" /> : null}
            </div>
          </div>
        </div>
      </div>

      {/* Explainability strip — the literal arithmetic behind the two gauges
          and the confidence percentage above, so trust in the headline
          numbers doesn't depend on trusting a black box. */}
      {contributors.length || confidenceDrivers.length ? (
        <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6 border-t border-slate-100 pt-5">
          {contributors.length ? (
            <WhyPanel label="Why this Recon Score?" openLabel="Hide Recon Score breakdown">
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
              {reconciliationScoreBreakdown?.formula ? (
                <p className="mt-3 text-slate-400 font-medium text-[11px] leading-relaxed m-0">{reconciliationScoreBreakdown.formula}</p>
              ) : null}
            </WhyPanel>
          ) : null}

          {confidenceDrivers.length ? (
            <WhyPanel label="Why this confidence?" openLabel="Hide confidence drivers">
              <div className="space-y-2.5">
                {confidenceDrivers.map((d) => (
                  <div key={d.name} className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-slate-700 font-bold text-xs">{d.shortLabel || d.name}</div>
                      {d.detail ? <div className="text-slate-400 font-medium text-[11px] leading-relaxed mt-0.5">{d.detail}</div> : null}
                    </div>
                    <div className="flex flex-shrink-0 items-center gap-2">
                      {d.weightPct != null ? <span className="text-slate-400 font-bold text-[11px] tabular-nums">{d.weightPct}% weight</span> : null}
                      <StatusPill tone={toneForLevel(d.status)}>{d.status}</StatusPill>
                    </div>
                  </div>
                ))}
              </div>
            </WhyPanel>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
