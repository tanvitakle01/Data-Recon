import React from "react";
import RiskBadge from "./RiskBadge";
import EmptyState from "./EmptyState";

function ConfidenceBar({ value }) {
  const v = Number(value);
  if (!Number.isFinite(v)) return null;
  const pct = Math.max(0, Math.min(100, v));
  return (
    <div className="mt-2">
      <div className="flex items-center justify-between">
        <div className="text-slate-500 font-bold text-xs">Confidence</div>
        <div className="text-slate-900 font-extrabold text-xs">{pct}%</div>
      </div>
      <div className="mt-2 h-3 rounded-full bg-slate-200 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function PatternIntelligenceCard({ operationalIntelligence }) {
  const patterns = operationalIntelligence?.patternIntelligence?.patterns ?? [];

  if (!Array.isArray(patterns) || patterns.length === 0) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
        <div className="text-slate-900 font-extrabold mb-3">Pattern Intelligence</div>
        <EmptyState
          title="No pattern insights available yet."
          subtitle="Generate insights from a reconciliation run to enable pattern intelligence."
        />
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
      <div className="text-slate-900 font-extrabold mb-3">Pattern Intelligence</div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {patterns.slice(0, 8).map((p, idx) => {
          const pattern = p?.pattern ?? p?.label ?? "Pattern";
          const frequency = p?.frequency ?? p?.freq;
          const affected = Array.isArray(p?.affectedDimensions)
            ? p.affectedDimensions.join(", ")
            : p?.affectedDimensions ?? "—";
          const confidence = p?.confidence;

          // Map confidence to risk color using same badge logic (based on <60 / 60-85 / >85)
          return (
            <div key={idx} className="rounded-2xl border border-slate-200 bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-slate-900 font-extrabold">{pattern}</div>
                  <div className="mt-1 text-slate-600 font-bold text-sm">
                    Impact frequency: {frequency ?? "—"}
                  </div>
                </div>
                <RiskBadge scoreOrAccuracy={confidence ?? 0} />
              </div>

              <div className="mt-3 text-slate-500 font-bold text-sm">
                Affected dimensions: <span className="text-slate-900 font-extrabold">{affected}</span>
              </div>
              <ConfidenceBar value={confidence} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

