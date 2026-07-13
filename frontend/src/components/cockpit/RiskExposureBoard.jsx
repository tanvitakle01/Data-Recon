import { FiEye, FiCalendar, FiTruck, FiFileText, FiTrendingUp } from "react-icons/fi";
import { SectionShell, StatusPill } from "./CockpitPrimitives";
import { toneForLevel } from "./cockpitUtils";
import { useCockpitFilter } from "./useCockpitFilter";

const RISK_LENS_ICON = {
  "Inventory Visibility Risk": FiEye,
  "Planning Risk": FiCalendar,
  "Fulfillment Risk": FiTruck,
  "Reporting Risk": FiFileText,
  "Forecast Accuracy Risk": FiTrendingUp,
};

const LEVEL_RANK = { High: 3, Medium: 2, Low: 1 };
const LEVEL_METER = { High: 92, Medium: 56, Low: 24 };
const LEVEL_COLOR = { High: "#ef4444", Medium: "#f59e0b", Low: "#94a3b8" };

/**
 * Section 6 — a board-level risk review: one "impact ladder" ranked by
 * severity (the visual IS the card — icon, severity meter and business
 * language in a single row) instead of a grid of equal-weight KPI cards.
 * Removed entirely when there's nothing to show.
 */
export default function RiskExposureBoard({ businessImpact }) {
  const { drillTo } = useCockpitFilter();
  const impacts = Array.isArray(businessImpact) ? businessImpact : [];
  if (impacts.length === 0) return null;

  const ranked = [...impacts].sort((a, b) => (LEVEL_RANK[b.level] || 0) - (LEVEL_RANK[a.level] || 0));

  const distribution = ["High", "Medium", "Low"]
    .map((level) => ({ level, count: impacts.filter((i) => i.level === level).length }))
    .filter((d) => d.count > 0);

  return (
    <SectionShell step="06" eyebrow="Business Risk · Impact Ladder" title="Risk Exposure Board">
      {distribution.length > 1 ? (
        <div className="mb-5">
          <div className="text-slate-400 font-black text-[11px] uppercase tracking-wide mb-2">Risk Distribution</div>
          <div className="flex h-3 w-full rounded-full overflow-hidden bg-slate-100">
            {distribution.map((d) => (
              <div
                key={d.level}
                style={{ width: `${(d.count / impacts.length) * 100}%`, background: LEVEL_COLOR[d.level] }}
                title={`${d.level}: ${d.count} area${d.count === 1 ? "" : "s"}`}
              />
            ))}
          </div>
        </div>
      ) : null}

      <div className="space-y-1">
        {ranked.map((impact, idx) => {
          const Icon = RISK_LENS_ICON[impact.riskArea] || FiEye;
          const color = LEVEL_COLOR[impact.level] || "#94a3b8";
          return (
            <button
              key={impact.riskArea}
              type="button"
              onClick={() => drillTo({ dimension: null, value: null, label: impact.riskArea, evidence: impact.recommendation, source: "businessImpact" })}
              className="flex w-full items-center gap-4 rounded-2xl px-2 py-3 text-left hover:bg-slate-50/80 transition-colors"
            >
              <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-slate-100">
                <Icon className="text-slate-600" size={18} />
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-3 mb-1.5">
                  <span className={`font-extrabold truncate ${idx === 0 ? "text-slate-900 text-base" : "text-slate-600 text-sm"}`}>{impact.riskArea}</span>
                  <StatusPill tone={toneForLevel(impact.level)}>{impact.level}</StatusPill>
                </div>
                <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden mb-1.5">
                  <div className="h-full rounded-full transition-[width] duration-700 ease-out" style={{ width: `${LEVEL_METER[impact.level] || 24}%`, background: color }} />
                </div>
                <div className="text-slate-400 font-medium text-xs leading-relaxed truncate">{impact.recommendation}</div>
              </div>

              <div className="flex-shrink-0 text-right w-16">
                <div className="text-slate-900 font-black text-sm tabular-nums">{impact.affectedRecords}</div>
                <div className="text-slate-400 font-bold text-[9px] uppercase tracking-wide">records</div>
              </div>
            </button>
          );
        })}
      </div>
    </SectionShell>
  );
}
