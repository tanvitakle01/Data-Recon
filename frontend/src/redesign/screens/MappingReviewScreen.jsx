import { useState } from "react";
import { ArrowLeft, Lock, Boxes, MapPin } from "lucide-react";
import { StepHeader } from "../components/StepHeader";
import { SectionCard } from "../components/SectionCard";
import { Tabs } from "../components/Tabs";
import { TierBadge } from "../components/Badge";
import { TierSummary } from "../components/TierSummary";
import { DataTable } from "../components/DataTable";
import { Button } from "../components/Button";
import { useStagger } from "../lib/useGsap";
import { VALUE_MAPPINGS, PRODUCT_TIER_COUNTS, LOCATION_TIER_COUNTS } from "../lib/sampleData";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "very_high", label: "VERY_HIGH" },
  { value: "high", label: "HIGH" },
  { value: "medium", label: "MEDIUM" },
  { value: "none", label: "Unmapped" },
  { value: "out_of_scope", label: "Excluded" },
];

const LOCATION_ROWS = [
  { src: "1010", tgt: "LOC-1010", tier: "very_high", rule: "location.rule1_exact_id", evidence: "Exact plant→location code match." },
  { src: "2020", tgt: "LOC-2020", tier: "very_high", rule: "location.rule1_exact_id", evidence: "Exact match." },
  { src: "PLNT-X", tgt: "LOC-3030", tier: "high", rule: "location.rule2_embedded_code", evidence: "Embedded code recovered from LOCNAME." },
  { src: "9999", tgt: "—", tier: "none", rule: "location.rule3_no_match", evidence: "No candidate above threshold." },
];

function EntitySection({ index, title, icon, fieldPair, counts, rows }) {
  const [filter, setFilter] = useState("all");
  const filtered = filter === "all" ? rows : rows.filter((r) => r.tier === filter);
  const columns = [
    { key: "src", header: "Source Value", mono: true, width: "18%" },
    { key: "tgt", header: "Matched Target Value", mono: true, width: "18%" },
    { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.tier} /> },
    { key: "rule", header: "Rule", mono: true, width: "24%" },
    { key: "evidence", header: "Evidence", render: (r) => <span className="text-text-secondary">{r.evidence}</span> },
  ];
  return (
    <SectionCard
      index={index} title={title} icon={icon}
      description={<span className="font-mono text-[12px]">{fieldPair}</span>}
      bodyClassName="flex flex-col gap-4"
    >
      <TierSummary counts={counts} />
      <div className="flex items-center justify-between gap-4">
        <Tabs variant="pill" value={filter} onChange={setFilter} items={FILTERS} />
        <span className="text-[12px] text-muted">{filtered.length} shown</span>
      </div>
      <DataTable columns={columns} rows={filtered} className="max-h-[360px]" emptyLabel="No values in this tier" />
    </SectionCard>
  );
}

export function MappingReviewScreen({ onBack }) {
  const ref = useStagger([]);
  return (
    <div className="flex h-full flex-col">
      <StepHeader
        eyebrow="Mapping · Review"
        title="Value mapping review"
        description="Every source value, its matched target, the rule that decided it, and the evidence — grouped by entity."
        actions={
          <>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 text-[12px] font-medium text-muted"><Lock className="h-3.5 w-3.5" /> Read-only</span>
            <Button variant="secondary" onClick={onBack}><ArrowLeft className="h-4 w-4" /> Back to mapping</Button>
          </>
        }
      />
      <div ref={ref} className="flex flex-col gap-5 overflow-y-auto px-8 py-6">
        <EntitySection index="1" title="Material → Product" icon={<Boxes className="h-4 w-4" />}
          fieldPair="Material → PRDID" counts={PRODUCT_TIER_COUNTS} rows={VALUE_MAPPINGS} />
        <EntitySection index="2" title="Plant → Location" icon={<MapPin className="h-4 w-4" />}
          fieldPair="ProductionPlant → LOCID" counts={LOCATION_TIER_COUNTS} rows={LOCATION_ROWS} />
      </div>
    </div>
  );
}

export default MappingReviewScreen;
