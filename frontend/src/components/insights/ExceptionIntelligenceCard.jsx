import React from "react";
import RiskBadge from "./RiskBadge";
import EmptyState from "./EmptyState";

function SeverityBar({ score }) {
  const s = Number(score);
  if (!Number.isFinite(s)) return null;
  const pct = Math.max(0, Math.min(100, s));
  return (
    <div className="mt-2">
      <div className="flex items-center justify-between">
        <div className="text-slate-500 font-bold text-xs">Severity score</div>
        <div className="text-slate-900 font-extrabold text-xs">{pct}</div>
      </div>
      <div className="mt-2 h-3 rounded-full bg-slate-200 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-red-500 to-amber-400"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function ExceptionIntelligenceCard({ operationalIntelligence, summary }) {
  const exceptions = operationalIntelligence?.exceptionIntelligence?.criticalExceptions ?? [];

  // Fallback from summary for “financial exposure”
  const financialExposure =
    summary?.financialExposure ?? summary?.financial_exposure ?? summary?.exposure;
  const impactedBusinessArea = summary?.businessArea ?? summary?.business_area;
  const occurrences = summary?.repeatOccurrenceCount ?? summary?.repeat_occurrence_count;

  if (!Array.isArray(exceptions) || exceptions.length === 0) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
        <div className="text-slate-900 font-extrabold mb-3">Critical Exception Summary</div>
        <EmptyState
          title="No supplier exceptions detected."
          subtitle="Run another reconciliation to surface exception intelligence."
        />
      </div>
    );
  }

  const top = exceptions.slice(0, 6);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
      <div className="text-slate-900 font-extrabold mb-3">Critical Exception Summary</div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <ul className="space-y-1">
            <li className="text-slate-800 font-semibold">• Missing in Target records detected.</li>
            <li className="text-slate-800 font-semibold">
              • Financial exposure: {financialExposure != null ? `₹${financialExposure}` : "—"}.
            </li>
            <li className="text-slate-800 font-semibold">
              • Repeat occurrence count: {occurrences != null ? occurrences : "—"}.
            </li>
            <li className="text-slate-800 font-semibold">
              • Business area impacted: {impactedBusinessArea ?? "—"}.
            </li>
          </ul>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-slate-900 font-extrabold mb-3">Exception severity (top items)</div>
          <div className="space-y-3">
            {top.map((e, idx) => {
              const category = e?.category ?? e?.anomalyType ?? e?.exceptionType ?? e?.type ?? "Exception";
              const severity = e?.severity ?? e?.priority ?? "Low";
              const score = e?.score ?? e?.severityScore ?? e?.risk_score ?? e?.riskScore;
              const entities = e?.impactedEntities ?? e?.entities ?? e?.entity ?? "—";

              return (
                <div key={idx} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-slate-900 font-extrabold">{category}</div>
                      <div className="text-slate-600 font-bold text-sm mt-1">Impacted: {Array.isArray(entities) ? entities.join(", ") : entities}</div>
                    </div>
                    <RiskBadge scoreOrAccuracy={score ?? 0} />
                  </div>
                  <SeverityBar score={score ?? severity} />
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

