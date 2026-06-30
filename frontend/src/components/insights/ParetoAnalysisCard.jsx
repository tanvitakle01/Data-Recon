import React from "react";
import EmptyState from "./EmptyState";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Line,
  CartesianGrid,
} from "recharts";

function SafeTop(list) {
  return Array.isArray(list) ? list : [];
}

export default function ParetoAnalysisCard({ operationalIntelligence }) {
  const pareto = operationalIntelligence?.paretoAnalysis ?? null;

  const plants = pareto?.plants ?? {};
  const materials = pareto?.materials ?? {};
  const suppliers = pareto?.suppliers ?? {};

  const makeChartData = (block) => {
    const top = SafeTop(block?.topContributors);
    return top.map((x, idx) => ({
      entity: x?.entity ?? x?.name ?? x?.plant ?? x?.material ?? `Contributor ${idx + 1}`,
      count: Number(x?.count ?? x?.exceptions ?? x?.value ?? 0),
      share: Number(x?.share ?? 0),
    }));
  };

  const charts = [
    { key: "plants", label: "Plants", block: plants },
    { key: "materials", label: "Materials", block: materials },
    { key: "suppliers", label: "Suppliers", block: suppliers },
  ];

  const isEmptySuppliers = !Array.isArray(suppliers?.topContributors) || suppliers?.topContributors?.length === 0;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
      <div className="text-slate-900 font-extrabold mb-3">Pareto Analysis (80/20)</div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {charts.map((c) => {
          const data = makeChartData(c.block);
          const hasData = data.length > 0;
          const showEmpty = c.key === "suppliers" ? isEmptySuppliers : !hasData;

          return (
            <div key={c.key} className="rounded-2xl border border-slate-200 bg-white p-3">
              <div className="flex items-baseline justify-between gap-3">
                <div className="font-extrabold text-slate-900">{c.label}</div>
                <div className="text-slate-500 font-bold text-xs">80% coverage</div>
              </div>

              {showEmpty ? (
                <div className="mt-3">
                  {c.key === "suppliers" ? (
                    <EmptyState title="No supplier-level exception concentration detected." />
                  ) : (
                    <EmptyState title="No Pareto data available yet." subtitle="Run a reconciliation to compute concentration." />
                  )}
                </div>
              ) : (
                <div className="mt-3 h-[330px] min-h-[300px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="entity" tick={{ fontSize: 12 }} interval={0} />
                      <YAxis />
                      <Tooltip />
                      <Bar dataKey="count" fill="#3b82f6" />
                      {/* Overlay share/cumulative approximation line */}
                      <Line type="monotone" dataKey="share" stroke="#10b981" strokeWidth={3} dot={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}


