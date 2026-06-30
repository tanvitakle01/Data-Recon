
import EmptyState from "./EmptyState";
import SkeletonCards from "./SkeletonCards";
import ExecutiveSummaryCard from "./ExecutiveSummaryCard";
import PatternIntelligenceCard from "./PatternIntelligenceCard";
import ExceptionIntelligenceCard from "./ExceptionIntelligenceCard";
import TrendIntelligenceCard from "./TrendIntelligenceCard";
import ParetoAnalysisCard from "./ParetoAnalysisCard";
import RiskEntitiesCard from "./RiskEntitiesCard";
import ComparisonCard from "./ComparisonCard";

function KpiMetricsGrid({ summary }) {
  const items = [
    { label: "Accuracy %", value: `${Number(summary?.accuracy ?? 0)}%` },
    { label: "Total Mismatches", value: summary?.mismatchedRecords ?? summary?.mismatched_records ?? 0 },
    { label: "Missing Records", value: summary?.missing_in_target ?? summary?.missingInTarget ?? 0 },
    { label: "Extra Records", value: summary?.extra_in_target ?? summary?.extraInTarget ?? 0 },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
      {items.map((it) => (
        <div key={it.label} className="rounded-2xl border border-slate-200 bg-white/70 p-4 shadow-sm">
          <div className="text-slate-500 font-extrabold text-xs">{it.label}</div>
          <div className="mt-2 text-slate-900 font-extrabold text-2xl">{it.value}</div>
        </div>
      ))}
    </div>
  );
}

export default function OperationalIntelligenceCenter({
  operationalIntelligence,
  summary,
  insights,
  loading,
  error,
}) {
  if (loading) {
    return (
      <div>
        <div className="text-slate-700 font-extrabold mb-2">Loading Operational Intelligence…</div>
        <SkeletonCards />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50/40 p-4">
        <div className="text-red-900 font-extrabold">Failed to load insights</div>
        <div className="mt-2 text-red-800 font-semibold text-sm">{String(error)}</div>
      </div>
    );
  }

  const oi = operationalIntelligence ?? {};

  const aiInsights = Array.isArray(insights) ? insights : [];
  const payloadRecommendations = operationalIntelligence?.recommendations ?? [];


  const hasAny =
    (oi?.patternIntelligence?.patterns?.length ?? 0) > 0 ||
    (oi?.exceptionIntelligence?.criticalExceptions?.length ?? 0) > 0 ||
    (oi?.trendIntelligence?.trendInsights?.length ?? 0) > 0 ||
    (oi?.paretoAnalysis ? 1 : 0) ||
    (oi?.riskEntities?.length ?? 0) > 0 ||
    (oi?.comparisonIntelligence?.comparisons?.length ?? 0) > 0;

  if (!hasAny) {
    return (
      <EmptyState
        title="No operational intelligence available.
"
        subtitle="Generate a reconciliation run to unlock AI analytics."
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Row 1 */}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">
        <div className="xl:col-span-3">
          <ExecutiveSummaryCard summary={summary ?? {}} />
        </div>
        <div className="xl:col-span-2">
          <KpiMetricsGrid summary={summary ?? {}} kpis={[]} />
        </div>
      </div>

      {/* AI Insights + Recommendations */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
          <div className="text-slate-900 font-extrabold mb-2">AI Insights</div>
          {aiInsights.length ? (
            <ul className="space-y-2">
              {aiInsights.map((t, idx) => (
                <li key={idx} className="text-slate-800 font-semibold">• {t}</li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No insights generated." subtitle="Run the insights engine to compute AI narratives." />
          )}
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
          <div className="text-slate-900 font-extrabold mb-2">Recommendations</div>
          <div className="text-slate-500 font-bold text-sm mb-3">
            Recommendations are derived from detected patterns.
          </div>
          {(Array.isArray(payloadRecommendations) ? payloadRecommendations : []).length ? (
            <ul className="space-y-2">
              {payloadRecommendations.slice(0, 5).map((t, idx) => (
                <li key={idx} className="text-slate-800 font-semibold">• {t}</li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No recommendations available." subtitle="Run another reconciliation to compute actions." />
          )}
        </div>
      </div>

      {/* Row 2: Exception + Pattern */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <ExceptionIntelligenceCard operationalIntelligence={oi} summary={summary ?? {}} />
        <PatternIntelligenceCard operationalIntelligence={oi} />
      </div>

      {/* Row 3 */}
      <ParetoAnalysisCard operationalIntelligence={oi} />

      {/* Row 4 */}
      <RiskEntitiesCard operationalIntelligence={oi} />

      {/* Row 5 */}
      <ComparisonCard operationalIntelligence={oi} />

      {/* Row 6 */}
      <TrendIntelligenceCard operationalIntelligence={oi} />
    </div>
  );
}

