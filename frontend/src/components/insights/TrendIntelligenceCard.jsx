import React from "react";
import EmptyState from "./EmptyState";
import RiskBadge from "./RiskBadge";

export default function TrendIntelligenceCard({ operationalIntelligence }) {
  const trends = operationalIntelligence?.trendIntelligence?.trendInsights ?? [];

  if (!Array.isArray(trends) || trends.length === 0) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
        <div className="text-slate-900 font-extrabold mb-3">Trend Analysis</div>
        <EmptyState
          title="No historical reconciliation runs available yet."
          subtitle="Upload additional comparison reports to enable trend analysis."
        />
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
      <div className="text-slate-900 font-extrabold mb-3">Trend Analysis</div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {trends.slice(0, 8).map((t, idx) => {
          const entity = t?.entity ?? t?.label ?? "Trend";
          const direction = t?.direction ?? t?.trend ?? "—";
          const growth = t?.changePct ?? t?.growth ?? t?.slope ?? t?.change ?? t?.acceleration;
          const timeRange = t?.timeRange ?? t?.time_range ?? t?.range ?? "—";

          const isDown = String(direction).toLowerCase().includes("down") || String(direction).toLowerCase().includes("decreasing");
          return (
            <div key={idx} className="rounded-2xl border border-slate-200 bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-slate-900 font-extrabold">{entity}</div>
                  <div className="mt-1 text-slate-600 font-bold text-sm">Direction: {direction}</div>
                </div>
                <RiskBadge scoreOrAccuracy={isDown ? 50 : 90} />
              </div>

              <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
                  <div className="text-slate-500 text-xs font-bold">Slope / Change %</div>
                  <div className="text-slate-900 font-extrabold mt-1">{growth ?? "—"}</div>
                </div>
                <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
                  <div className="text-slate-500 text-xs font-bold">Time range</div>
                  <div className="text-slate-900 font-extrabold mt-1">{timeRange}</div>
                </div>
              </div>

              <div className="mt-3 h-10 rounded-xl bg-gradient-to-r from-blue-500/10 to-emerald-500/10" />
            </div>
          );
        })}
      </div>
    </div>
  );
}

