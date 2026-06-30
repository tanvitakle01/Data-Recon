import React from "react";
import RiskBadge from "./RiskBadge";

function ListBullet({ children }) {
  return (
    <li className="text-slate-800 font-semibold">• {children}</li>
  );
}

export default function ExecutiveSummaryCard({ summary }) {
  const accuracy = Number(summary?.accuracy ?? summary?.Accuracy ?? 0);
  const statusScore = Number.isFinite(accuracy) ? accuracy : 0;

  const mismatchedRecords = summary?.mismatchedRecords ?? summary?.mismatched_records;
  const missingInTarget =
    summary?.missing_in_target ?? summary?.missingInTarget ?? summary?.missingInTargetCount;
  const extraInTarget =
    summary?.extra_in_target ?? summary?.extraInTarget ?? summary?.extraInTargetCount;
  const qtyMismatches = summary?.qtyMismatch ?? summary?.qty_mismatch ?? summary?.quantityMismatch;
  const plantsAffected = summary?.plantsAffected ?? summary?.plants_affected;
  const materialsAffected = summary?.materialsAffected ?? summary?.materials_affected;

  const keyFindings = [
    mismatchedRecords != null ? `${mismatchedRecords} reconciliation exceptions found` : null,
    missingInTarget != null ? `${missingInTarget} records missing in target` : null,
    extraInTarget != null ? `${extraInTarget} unexpected records found` : null,
    qtyMismatches != null ? `${qtyMismatches} quantity mismatches detected` : null,
    plantsAffected != null ? `${plantsAffected} plants affected` : null,
    materialsAffected != null ? `${materialsAffected} materials affected` : null,
  ].filter(Boolean);

  const businessImpact = [
    "Inventory visibility risk",
    "Planning accuracy degradation",
    "Potential fulfillment delays",
  ];

  return (
    <div className="rounded-3xl border border-slate-200 bg-gradient-to-b from-white/90 to-white/60 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-slate-900 font-extrabold text-lg">Operational Health Score</div>
          <div className="mt-1 text-slate-500 font-bold">Accuracy: {Number.isFinite(accuracy) ? `${accuracy}%` : "—"}</div>
        </div>
        <RiskBadge scoreOrAccuracy={statusScore} />
      </div>

      <div className="mt-4">
        <div className="text-slate-900 font-extrabold text-sm">Key Findings:</div>
        <ul className="mt-2 space-y-1">
          {keyFindings.length ? (
            keyFindings.map((x) => <ListBullet key={x}>{x}</ListBullet>)
          ) : (
            <li className="text-slate-500 font-semibold">• No key findings available.</li>
          )}
        </ul>
      </div>

      <div className="mt-4">
        <div className="text-slate-900 font-extrabold text-sm">Business Impact:</div>
        <ul className="mt-2 space-y-1">
          {businessImpact.map((x) => (
            <ListBullet key={x}>{x}</ListBullet>
          ))}
        </ul>
      </div>
    </div>
  );
}

