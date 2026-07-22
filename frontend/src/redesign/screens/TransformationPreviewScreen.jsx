import { ArrowLeft, Check, X, Download, Wand2 } from "lucide-react";
import { StepHeader } from "../components/StepHeader";
import { SectionCard } from "../components/SectionCard";
import { Button } from "../components/Button";
import { Badge, ChangeBadge } from "../components/Badge";
import { DataTable } from "../components/DataTable";
import { BeforeAfter } from "../components/BeforeAfter";
import { cn } from "../lib/cn";
import { useStagger } from "../lib/useGsap";
import { SHADOW_COLUMNS, SHADOW_ROWS } from "../lib/sampleData";

const LIFECYCLE = [
  { label: "Mapping sheet", done: true },
  { label: "Transformation generated", done: true },
  { label: "Preview executed", done: true },
  { label: "Approved", done: false },
];

const MODIFIED_COLUMNS = [
  { col: "Material", change: "modified", from: "000000004711", to: "4711" },
  { col: "ProductionPlant", change: "modified", from: "1010", to: "LOC-1010" },
  { col: "RequestedDeliveryDate", change: "modified", from: "2026-03-14", to: "2026-03" },
  { col: "RequestedQuantity", change: "aggregated", from: "620 + 620", to: "1,240" },
];

export function TransformationPreviewScreen({ onBack }) {
  const ref = useStagger([]);
  const columns = [
    { key: "col", header: "Column", mono: true, width: "30%" },
    { key: "change", header: "Change", render: (r) => <ChangeBadge change={r.change} /> },
    { key: "from", header: "From", mono: true, render: (r) => <span className="text-muted">{r.from}</span> },
    { key: "to", header: "To", mono: true, render: (r) => <span className="font-medium text-text">{r.to}</span> },
  ];
  return (
    <div className="flex h-full flex-col">
      <StepHeader
        eyebrow="Mapping · Preview"
        title="Transformation preview"
        description="You approve the transformed data, never the code. Review the changes, then approve or reject."
        actions={<Button variant="secondary" onClick={onBack}><ArrowLeft className="h-4 w-4" /> Back to mapping</Button>}
      />
      <div ref={ref} className="flex flex-col gap-5 overflow-y-auto px-8 py-6">
        {/* lifecycle */}
        <div className="flex flex-wrap items-center gap-2">
          {LIFECYCLE.map((s, i) => (
            <div key={s.label} className="flex items-center gap-2">
              <span className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-medium",
                s.done ? "border-match-bd bg-match-bg text-match-fg" : "border-line-2 bg-surface-2 text-muted"
              )}>
                <span className={cn("flex h-3.5 w-3.5 items-center justify-center rounded-full", s.done ? "bg-match-solid text-white" : "bg-line-3 text-white")}>
                  {s.done ? <Check className="h-2.5 w-2.5" strokeWidth={3} /> : i + 1}
                </span>
                {s.label}
              </span>
              {i < LIFECYCLE.length - 1 && <span className="h-px w-4 bg-line-2" />}
            </div>
          ))}
          <Badge status="high" className="ml-2">Confidence 0.86</Badge>
        </div>

        <SectionCard title="Modified columns" icon={<Wand2 className="h-4 w-4" />} bodyClassName="p-0">
          <DataTable columns={columns} rows={MODIFIED_COLUMNS} className="rounded-none border-0" />
        </SectionCard>

        <SectionCard title="Transformed data preview" description="Original source vs the transformed shadow source, row by row.">
          <BeforeAfter columns={SHADOW_COLUMNS} rows={SHADOW_ROWS} sourceCount={12480} shadowCount={9860} />
        </SectionCard>

        <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2/40 px-4 py-3">
          <p className="text-[13px] text-muted">Approving pins this transformation for the reconciliation run.</p>
          <div className="flex items-center gap-2">
            <Button variant="ghost"><Download className="h-4 w-4" /> Download CSV</Button>
            <Button variant="secondary"><X className="h-4 w-4" /> Reject</Button>
            <Button variant="primary"><Check className="h-4 w-4" /> Approve transformation</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default TransformationPreviewScreen;
