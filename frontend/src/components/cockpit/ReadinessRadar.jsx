import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { SectionShell, StatusPill, WhyPanel } from "./CockpitPrimitives";
import { toneForLevel, scoreToHex } from "./cockpitUtils";

const STATUS_VALUE = { Pass: 100, Partial: 50, Fail: 0 };
const EMPTY_FACTORS = [];

/**
 * Section 4 — Trust Assessment. The old version buried this in a collapsed
 * accordion of text; here it's a dedicated section with a radar chart doing
 * the explaining visually — a lopsided shape immediately shows *which*
 * factors are failing, which a list of Pass/Partial/Fail rows never
 * communicates as fast.
 */
export default function ReadinessRadar({ readiness }) {
  const score = Number(readiness?.score ?? 100);
  const factors = Array.isArray(readiness?.factors) ? readiness.factors : EMPTY_FACTORS;

  const option = useMemo(() => {
    if (!factors.length) return null;
    const indicator = factors.map((f) => ({ name: f.name, max: 100 }));
    const values = factors.map((f) => STATUS_VALUE[f.status] ?? 0);
    const tone = scoreToHex(score);

    return {
      tooltip: { trigger: "item" },
      radar: {
        indicator,
        radius: "68%",
        splitNumber: 4,
        axisName: { color: "#64748b", fontSize: 11, fontWeight: 700 },
        splitArea: { areaStyle: { color: ["#f8fafc", "#ffffff"] } },
        axisLine: { lineStyle: { color: "#e2e8f0" } },
        splitLine: { lineStyle: { color: "#e2e8f0" } },
      },
      series: [
        {
          type: "radar",
          data: [
            {
              value: values,
              name: "Readiness",
              areaStyle: { color: tone, opacity: 0.18 },
              lineStyle: { color: tone, width: 2 },
              itemStyle: { color: tone },
            },
          ],
        },
      ],
    };
  }, [factors, score]);

  if (!factors.length) return null;

  return (
    <SectionShell step="04" eyebrow="Trust Assessment · Can This Be Trusted?" title="Readiness Radar">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-6 items-center">
        <div style={{ height: 260 }}>
          <ReactECharts option={option} style={{ height: "100%", width: "100%" }} />
        </div>

        <div>
          <div className="text-slate-400 font-bold text-xs uppercase tracking-wide mb-1">Readiness Score</div>
          <div className="font-black text-5xl tabular-nums mb-2" style={{ color: scoreToHex(score) }}>
            {score}%
          </div>
          <p className="text-slate-500 font-medium text-sm leading-relaxed mb-4">{readiness?.reason}</p>
          <div className="space-y-2.5">
            {factors.map((f) => (
              <div key={f.name} className="flex items-center justify-between gap-2">
                <span className="text-slate-600 font-bold text-xs truncate">{f.name}</span>
                <div className="flex flex-shrink-0 items-center gap-2">
                  {f.weightPct != null ? (
                    <span className="text-slate-400 font-bold text-[11px] tabular-nums" title={`${f.weightPct}% of total weight × ${f.statusScore ?? 0} status score = ${f.contributionPoints ?? 0} pts`}>
                      {f.contributionPoints ?? 0}/{f.weightPct}% pts
                    </span>
                  ) : null}
                  <StatusPill tone={toneForLevel(f.status)}>{f.status}</StatusPill>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {readiness?.formula ? (
        <div className="mt-6 border-t border-slate-100 pt-4">
          <WhyPanel label="Why this readiness score?" openLabel="Hide the math">
            <div className="space-y-2">
              {factors.map((f) => (
                <div key={f.name} className="flex items-center justify-between gap-3 text-xs">
                  <span className="text-slate-600 font-bold truncate">{f.name}</span>
                  <span className="text-slate-400 font-semibold tabular-nums flex-shrink-0">
                    {f.statusScore ?? 0} status × {f.weightPct}% weight = <span className="text-slate-700 font-bold">{f.contributionPoints ?? 0} pts</span>
                  </span>
                </div>
              ))}
              <div className="flex items-center justify-between gap-3 text-xs border-t border-slate-200 pt-2 mt-1">
                <span className="text-slate-700 font-black">Weighted Readiness</span>
                <span className="text-slate-900 font-black tabular-nums">{score}%</span>
              </div>
            </div>
            <p className="mt-3 text-slate-400 font-medium text-[11px] leading-relaxed m-0">{readiness.formula}</p>
          </WhyPanel>
        </div>
      ) : null}
    </SectionShell>
  );
}
