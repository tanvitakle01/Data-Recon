import { Download, LineChart, CalendarClock } from "lucide-react";
import { StepHeader } from "../components/StepHeader";
import { StatTile } from "../components/TierSummary";
import { DataTable } from "../components/DataTable";
import { OutcomeBadge } from "../components/Badge";
import { Button } from "../components/Button";
import { SectionCard } from "../components/SectionCard";
import { cn } from "../lib/cn";
import { useStagger } from "../lib/useGsap";
import { RESULTS, RESULT_ROWS } from "../lib/sampleData";

export function ResultsScreen({ onBack }) {
  const ref = useStagger([]);
  const columns = [
    { key: "key", header: "Key (Product · Location · Period)", mono: true, width: "34%" },
    { key: "src", header: "Source Qty", align: "right", render: (r) => r.src.toLocaleString() },
    { key: "tgt", header: "Target Qty", align: "right", render: (r) => r.tgt.toLocaleString() },
    { key: "delta", header: "Δ", align: "right", render: (r) => (
      <span className={cn("tabular-nums font-medium", r.delta === 0 ? "text-muted" : r.delta > 0 ? "text-mismatch-fg" : "text-missing-fg")}>
        {r.delta > 0 ? "+" : ""}{r.delta.toLocaleString()}
      </span>
    ) },
    { key: "outcome", header: "Outcome", render: (r) => <OutcomeBadge outcome={r.outcome} /> },
  ];
  const matchRate = ((RESULTS.matches / RESULTS.total) * 100).toFixed(1);

  return (
    <div className="flex h-full flex-col">
      <StepHeader
        step={5} total={5} eyebrow="Results"
        title="Reconciliation results"
        description={`${matchRate}% match rate across ${RESULTS.total.toLocaleString()} reconciled records · contract_a1b2c3d4e5f6`}
        actions={
          <>
            <Button variant="ghost" onClick={onBack}>Back</Button>
            <Button variant="secondary"><LineChart className="h-4 w-4" /> View insights</Button>
            <Button variant="primary"><Download className="h-4 w-4" /> Download sheet</Button>
          </>
        }
      />
      <div ref={ref} className="flex flex-col gap-6 overflow-y-auto px-8 py-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <StatTile status="match" value={RESULTS.matches} label="Matches" />
          <StatTile status="mismatch" value={RESULTS.mismatches} label="Qty mismatches" />
          <StatTile status="extra" value={RESULTS.missingSource} label="Missing in source" />
          <StatTile status="missing" value={RESULTS.missingTarget} label="Missing in target" />
          <StatTile status="neutral" value={RESULTS.total} label="Total records" />
        </div>

        <SectionCard
          title="Comparison detail"
          description="Tolerance matches count as matches. Right-aligned numerics, mono keys."
          icon={<CalendarClock className="h-4 w-4" />}
          bodyClassName="p-0"
        >
          <DataTable columns={columns} rows={RESULT_ROWS} className="rounded-none border-0" zebra />
        </SectionCard>

        <div className="rounded-xl border border-line bg-surface-2/40 px-4 py-3 text-[13px] text-muted">
          <span className="font-medium text-text-secondary">Date alignment:</span> source 2026-03-01 → 2026-05-31 · target 2026-03 → 2026-05 · overlap 100% · 0 rows dropped.
        </div>
      </div>
    </div>
  );
}

export default ResultsScreen;
