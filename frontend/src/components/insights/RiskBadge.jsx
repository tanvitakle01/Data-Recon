import React from "react";

function getRiskMeta(riskAccuracyOrScore) {
  const n = Number(riskAccuracyOrScore);
  if (Number.isNaN(n)) {
    return { label: "Unknown", cls: "bg-slate-100 text-slate-700 border-slate-200" };
  }

  // Objective: Critical: Accuracy < 60%, Warning: 60-85%, Healthy: > 85%
  if (n < 60) {
    return { label: "🔴 Critical", cls: "bg-red-50 text-red-800 border-red-200" };
  }
  if (n <= 85) {
    return { label: "🟠 Warning", cls: "bg-orange-50 text-orange-800 border-orange-200" };
  }
  return { label: "🟢 Healthy", cls: "bg-emerald-50 text-emerald-800 border-emerald-200" };
}

export default function RiskBadge({ scoreOrAccuracy }) {
  const meta = getRiskMeta(scoreOrAccuracy);
  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-extrabold ${meta.cls}`}
    >
      {meta.label}
    </span>
  );
}

