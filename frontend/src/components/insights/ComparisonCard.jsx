import React from "react";
import EmptyState from "./EmptyState";

export default function ComparisonCard({ operationalIntelligence }) {
  const comparisons = operationalIntelligence?.comparisonIntelligence?.comparisons ?? [];

  if (!Array.isArray(comparisons) || comparisons.length === 0) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
        <div className="text-slate-900 font-extrabold mb-3">Comparison Intelligence</div>
        <EmptyState title="No comparison intelligence available." subtitle="Generate new reconciliation insights to compute comparisons." />
      </div>
    );
  }

  const top = comparisons.slice(0, 6);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
      <div className="text-slate-900 font-extrabold mb-3">Comparison Intelligence</div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {top.map((c, idx) => {
          const a = c?.entityA ?? c?.a ?? c?.left ?? "—";
          const b = c?.entityB ?? c?.b ?? c?.right ?? "—";
          const variance = c?.delta ?? c?.variance ?? c?.difference ?? c?.percentageDifference ?? c?.pctDiff ?? "—";
          const entityType = c?.entityType ?? c?.type ?? "Entity";

          return (
            <div key={idx} className="rounded-2xl border border-slate-200 bg-white p-4">
              <div className="text-slate-900 font-extrabold">{entityType}: {String(a)} vs {String(b)}</div>
              <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
                  <div className="text-slate-500 font-bold text-xs">Entity A</div>
                  <div className="text-slate-900 font-extrabold mt-1">{String(a)}</div>
                </div>
                <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
                  <div className="text-slate-500 font-bold text-xs">Entity B</div>
                  <div className="text-slate-900 font-extrabold mt-1">{String(b)}</div>
                </div>
                <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
                  <div className="text-slate-500 font-bold text-xs">Δ / % diff</div>
                  <div className="text-slate-900 font-extrabold mt-1">{String(variance)}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

