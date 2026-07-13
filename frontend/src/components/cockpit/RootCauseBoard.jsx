import { useState } from "react";
import { FiZap, FiInfo, FiArrowRight } from "react-icons/fi";
import { SectionShell, StatusPill } from "./CockpitPrimitives";
import { toneForLevel, scoreToHex } from "./cockpitUtils";
import { useCockpitFilter } from "./useCockpitFilter";

// Causes with a genuinely literal, filterable Remarks category. Everything
// else in the taxonomy (Master Data Misalignment, Date Range Mismatch,
// mapping gaps) doesn't map to one column value, so clicking those still
// opens the workspace but as descriptive context rather than a false-precision filter.
const CAUSE_TO_EXCEPTION_TYPE = {
  "Missing Transactions": "Missing in Target",
  "Quantity Variance": "Quantity Mismatch",
};

function humanizeMetricKey(key) {
  return key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^./, (c) => c.toUpperCase());
}

function formatMetricValue(key, value) {
  if (value == null) return "—";
  return key.toLowerCase().endsWith("pct") ? `${value}%` : String(value);
}

/**
 * Section 3 — investigation wall: causes as confidence-ranked bars (length
 * IS the confidence), not text cards. Evidence is progressive disclosure —
 * a click reveals it inline instead of every card carrying a paragraph by
 * default, which is what made the previous version feel text-heavy.
 */
export default function RootCauseBoard({ rootCauseExplorer, patternIntelligence }) {
  const { drillTo } = useCockpitFilter();
  const [expandedIdx, setExpandedIdx] = useState(null);
  const causes = Array.isArray(rootCauseExplorer) ? rootCauseExplorer : [];

  if (causes.length === 0) return null;

  const showPatterns = patternIntelligence?.show && (patternIntelligence?.patterns?.length ?? 0) > 0;
  const maxConfidence = causes[0].confidence || 1;

  const onExplore = (cause) => {
    const exceptionType = CAUSE_TO_EXCEPTION_TYPE[cause.cause];
    if (exceptionType) {
      drillTo({ dimension: "exceptionType", value: exceptionType, label: cause.cause, source: "rootCause" });
    } else {
      drillTo({ dimension: null, value: null, label: cause.cause, evidence: cause.evidence, source: "rootCause" });
    }
  };

  return (
    <SectionShell step="03" eyebrow="Why It Happened · Investigation" title="Root Cause Board">
      {showPatterns ? (
        <div className="mb-5 flex items-start gap-3 rounded-2xl border border-blue-100 bg-blue-50/60 p-3">
          <FiZap className="text-blue-500 mt-0.5 flex-shrink-0" />
          <div className="space-y-1">
            {patternIntelligence.patterns.slice(0, 2).map((p, idx) => (
              <div key={idx} className="text-blue-900 font-semibold text-sm">
                {p.pattern} <span className="text-blue-600 font-bold">({p.confidence}% confidence)</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="space-y-1">
        {causes.map((cause, idx) => {
          const tone = scoreToHex(cause.confidence);
          const barWidth = Math.max(4, Math.round((cause.confidence / maxConfidence) * 100));
          const isExpanded = expandedIdx === idx;
          return (
            <div key={cause.cause + idx} className="rounded-2xl hover:bg-slate-50/80 transition-colors">
              <div className="flex items-center gap-4 px-2 py-3 cursor-pointer" onClick={() => onExplore(cause)}>
                <div className="w-7 text-slate-300 font-black text-sm tabular-nums flex-shrink-0">{idx + 1}</div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-3 mb-1.5">
                    <span className={`font-extrabold truncate ${idx === 0 ? "text-slate-900 text-base" : "text-slate-600 text-sm"}`}>{cause.cause}</span>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <StatusPill tone={toneForLevel(cause.impact)}>{cause.impact}</StatusPill>
                      <span className="text-slate-400 font-bold text-xs">{cause.affectedRecords} rec.</span>
                    </div>
                  </div>
                  <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
                    <div className="h-full rounded-full transition-[width] duration-700 ease-out" style={{ width: `${barWidth}%`, background: tone }} />
                  </div>
                </div>

                <div className="w-14 text-right flex-shrink-0">
                  <span className="font-black text-lg tabular-nums" style={{ color: tone }}>{cause.confidence}%</span>
                </div>

                {cause.evidence ? (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpandedIdx(isExpanded ? null : idx);
                    }}
                    className="flex-shrink-0 flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 text-slate-400 hover:border-blue-300 hover:text-blue-500"
                    aria-label="Toggle evidence"
                  >
                    <FiInfo size={13} />
                  </button>
                ) : null}
              </div>

              {isExpanded ? (
                <div className="mx-2 mb-3 -mt-1 space-y-2">
                  {cause.evidence ? (
                    <div className="flex items-start gap-2 rounded-xl bg-slate-50 px-3 py-2.5">
                      <FiArrowRight className="text-slate-300 mt-0.5 flex-shrink-0" size={12} />
                      <p className="text-slate-500 font-medium text-xs leading-relaxed m-0">{cause.evidence}</p>
                    </div>
                  ) : null}

                  {cause.reasoning ? (
                    <div className="flex items-start gap-2 rounded-xl bg-blue-50/60 px-3 py-2.5">
                      <FiInfo className="text-blue-400 mt-0.5 flex-shrink-0" size={12} />
                      <p className="text-blue-800 font-semibold text-xs leading-relaxed m-0">
                        <span className="uppercase tracking-wide text-[10px] font-black text-blue-500 mr-1.5">How this % was derived</span>
                        {cause.reasoning}
                      </p>
                    </div>
                  ) : null}

                  {cause.metrics && Object.keys(cause.metrics).length ? (
                    <div className="flex flex-wrap gap-1.5 px-1">
                      {Object.entries(cause.metrics).map(([key, value]) => (
                        <span
                          key={key}
                          className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-bold text-slate-500"
                        >
                          {humanizeMetricKey(key)}: <span className="text-slate-800">{formatMetricValue(key, value)}</span>
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </SectionShell>
  );
}
