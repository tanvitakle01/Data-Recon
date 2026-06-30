import React from "react";

export default function EmptyState({
  title = "No data available yet.",
  subtitle,
}) {
  return (
    <div className="w-full rounded-2xl border border-slate-200 bg-white/70 p-4">
      <div className="text-slate-700 font-extrabold">{title}</div>
      {subtitle ? (
        <div className="mt-2 text-slate-500 font-semibold text-sm">{subtitle}</div>
      ) : null}
    </div>
  );
}

