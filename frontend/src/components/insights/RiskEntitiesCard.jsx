import React from "react";
import RiskBadge from "./RiskBadge";
import EmptyState from "./EmptyState";

export default function RiskEntitiesCard({ operationalIntelligence }) {
  const risks = operationalIntelligence?.riskEntities ?? [];

  if (!Array.isArray(risks) || risks.length === 0) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
        <div className="text-slate-900 font-extrabold mb-3">Risk Analysis</div>
        <EmptyState title="No risk entities detected." subtitle="Run insights to compute risk entities." />
      </div>
    );
  }

  const sorted = [...risks].sort((a, b) => Number(b?.riskScore ?? b?.risk_score ?? b?.score ?? 0) - Number(a?.riskScore ?? a?.risk_score ?? a?.score ?? 0));
  const top = sorted.slice(0, 5);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
      <div className="text-slate-900 font-extrabold mb-3">Top Risk Entities</div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-slate-900 font-extrabold mb-2">Risk ranking</div>
          <div className="space-y-3">
            {top.map((r, idx) => {
              const name = r?.entity ?? r?.name ?? r?.item ?? r?.material ?? "—";
              const score = r?.riskScore ?? r?.risk_score ?? r?.score;
              const factors = r?.contributingFactors ?? r?.factors ?? r?.drivers ?? [];

              return (
                <div key={idx} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-slate-900 font-extrabold">#{idx + 1} {name}</div>
                      <div className="mt-1 text-slate-600 font-bold text-sm">Risk Score: {score ?? "—"}</div>
                    </div>
                    <RiskBadge scoreOrAccuracy={Number(score ?? 0)} />
                  </div>
                  {Array.isArray(factors) && factors.length ? (
                    <div className="mt-2 text-slate-500 font-bold text-sm">Drivers: {factors.join(", ")}</div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-slate-900 font-extrabold mb-2">Business impact (top risks)</div>
          <div className="space-y-3">
            {top.map((r, idx) => {
              const name = r?.entity ?? r?.name ?? r?.item ?? r?.material ?? "—";
              const score = r?.riskScore ?? r?.risk_score ?? r?.score;
              const impact = r?.businessImpact ?? r?.impact ?? r?.business_impact;

              return (
                <div key={idx} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-slate-900 font-extrabold">{name}</div>
                      <div className="mt-1 text-slate-600 font-bold text-sm">Risk: {score ?? "—"}</div>
                    </div>
                    <RiskBadge scoreOrAccuracy={Number(score ?? 0)} />
                  </div>
                  <div className="mt-2 text-slate-500 font-bold text-sm">Impact: {impact ?? "—"}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

