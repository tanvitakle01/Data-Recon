import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, LineChart, Line, XAxis, YAxis } from "recharts";
import Counter from "../Counter";
import { SectionShell } from "./CockpitPrimitives";
import { useCockpitFilter } from "./useCockpitFilter";

const CATEGORY_META = {
  missing: { label: "Missing in Target", color: "#ef4444", exceptionType: "Missing in Target" },
  extra: { label: "Extra in Target", color: "#3b82f6", exceptionType: "Extra in Target" },
  qtyMismatch: { label: "Quantity Mismatch", color: "#f59e0b", exceptionType: "Quantity Mismatch" },
};

/**
 * Section 2 — "what is broken" as one composition, not three metric cards.
 * A single segmented bar (widths proportional to actual share) sits beside
 * the donut; the dominant category gets the biggest number and the longest
 * segment, insignificant categories physically take up less room instead of
 * an equal-size box each.
 */
export default function ExceptionCompositionPanel({ exceptionLandscape, trend }) {
  const { drillTo } = useCockpitFilter();
  if (!exceptionLandscape) return null;

  const trendPoints = Array.isArray(trend) ? trend : [];
  const hasTrend = trendPoints.length >= 2;

  const { missing, extra, qtyMismatch, dominantCategory, businessImpactEstimate } = exceptionLandscape;
  const buckets = { missing, extra, qtyMismatch };

  const ranked = Object.entries(CATEGORY_META)
    .map(([key, meta]) => ({ key, meta, bucket: buckets[key] }))
    .filter((r) => r.bucket && r.bucket.count > 0)
    .sort((a, b) => b.bucket.count - a.bucket.count);

  if (ranked.length === 0) return null;

  const total = ranked.reduce((sum, r) => sum + r.bucket.count, 0);
  const chartData = ranked.map((r) => ({ name: r.meta.label, value: r.bucket.count, color: r.meta.color }));
  const featured = ranked[0];

  return (
    <SectionShell step="02" eyebrow="What Is Broken · Composition" title="Exception Composition">
      <div className="grid grid-cols-1 lg:grid-cols-[auto_1fr] gap-8 items-center">
        <div className="relative h-[176px] w-[176px] mx-auto flex-shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={chartData} dataKey="value" nameKey="name" innerRadius={54} outerRadius={82} paddingAngle={2}>
                {chartData.map((d) => (
                  <Cell key={d.name} fill={d.color} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none px-4">
            <Counter value={featured.bucket.count} fontSize={30} fontWeight={800} textColor="#0F172A" gap={0} />
            <div className="text-slate-400 font-black text-[9px] uppercase tracking-wide text-center leading-tight mt-0.5">{dominantCategory}</div>
          </div>
        </div>

        <div className="min-w-0">
          {/* Single segmented composition bar — one visual, not N cards */}
          <div className="flex h-3 w-full rounded-full overflow-hidden bg-slate-100 mb-4">
            {ranked.map(({ key, meta, bucket }) => (
              <button
                key={key}
                type="button"
                onClick={() => drillTo({ dimension: "exceptionType", value: meta.exceptionType, label: meta.label, source: "exceptionComposition" })}
                style={{ width: `${Math.max(2, (bucket.count / total) * 100)}%`, background: meta.color }}
                className="h-full transition-opacity hover:opacity-80"
                title={`${meta.label}: ${bucket.distributionPct}%`}
              />
            ))}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-4 gap-y-3">
            {ranked.map(({ key, meta, bucket }, idx) => (
              <button
                key={key}
                type="button"
                onClick={() => drillTo({ dimension: "exceptionType", value: meta.exceptionType, label: meta.label, source: "exceptionComposition" })}
                className="text-left group"
              >
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="h-2 w-2 rounded-full flex-shrink-0" style={{ background: meta.color }} />
                  <span className={`font-bold truncate group-hover:text-blue-600 transition-colors ${idx === 0 ? "text-slate-700 text-xs" : "text-slate-400 text-[11px]"}`}>
                    {meta.label}
                  </span>
                </div>
                <div className={`font-black tabular-nums ${idx === 0 ? "text-slate-900 text-xl" : "text-slate-500 text-base"}`}>
                  {bucket.distributionPct}%
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {businessImpactEstimate?.affectedAreas ? (
        <div className="mt-5 pt-4 border-t border-slate-100 text-slate-400 font-semibold text-xs">
          Affecting {businessImpactEstimate.affectedAreas} business area{businessImpactEstimate.affectedAreas === 1 ? "" : "s"}
          {businessImpactEstimate.highSeverityAreas ? ` · ${businessImpactEstimate.highSeverityAreas} at high severity` : ""}
        </div>
      ) : null}

      {hasTrend ? (
        <div className="mt-5 pt-4 border-t border-slate-100">
          <div className="text-slate-400 font-black text-[11px] uppercase tracking-wide mb-2">Exception Volume Trend</div>
          <div style={{ height: 90 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendPoints} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <XAxis dataKey="period" tick={{ fontSize: 10, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                <YAxis hide />
                <Tooltip />
                <Line type="monotone" dataKey="mismatches" stroke="#2563eb" strokeWidth={2.5} dot={{ r: 2 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : null}
    </SectionShell>
  );
}
