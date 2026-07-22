import { useState } from "react";
import {
  ArrowLeft, ArrowRight, Wand2, Plus, Trash2, CheckCircle2, FileSpreadsheet,
  ListChecks, Sigma, Play, ShieldCheck, Eye, PencilRuler, Info,
} from "lucide-react";
import { StepHeader } from "../components/StepHeader";
import { SectionCard } from "../components/SectionCard";
import { Tabs } from "../components/Tabs";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Select } from "../components/Select";
import { Input } from "../components/Input";
import { Tooltip } from "../components/Tooltip";
import { FieldMappingTable } from "../components/FieldMappingTable";
import { BeforeAfter } from "../components/BeforeAfter";
import { TierSummary } from "../components/TierSummary";
import { useStagger } from "../lib/useGsap";
import {
  SHADOW_COLUMNS, SHADOW_ROWS, PRODUCT_TIER_COUNTS, LOCATION_TIER_COUNTS,
} from "../lib/sampleData";

const SOURCE_FIELDS = ["Material", "ProductionPlant", "RequestedDeliveryDate", "RequestedQuantity", "SalesOrderItemText"];

/* ---- small builders ------------------------------------------------------ */
function RuleRows({ label, hint, initial }) {
  const [rows, setRows] = useState(initial);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-medium text-text-secondary">{label}</span>
        <Tooltip content={hint}><Info className="h-3.5 w-3.5 text-faint" /></Tooltip>
      </div>
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2">
          <Select value={r.field} onChange={(e) => setRows((x) => x.map((y, j) => (j === i ? { ...y, field: e.target.value } : y)))} className="h-8 w-52 font-mono text-[12.5px]">
            {SOURCE_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
          </Select>
          <Input value={r.text} onChange={(e) => setRows((x) => x.map((y, j) => (j === i ? { ...y, text: e.target.value } : y)))} className="h-8 flex-1" placeholder="Describe the rule in plain language…" />
          <Button size="sm" variant="ghost" iconOnly aria-label="Remove" onClick={() => setRows((x) => x.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
        </div>
      ))}
      <button onClick={() => setRows((x) => [...x, { field: SOURCE_FIELDS[0], text: "" }])} className="inline-flex w-fit items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] font-medium text-accent-text transition-colors hover:bg-accent-tint">
        <Plus className="h-3.5 w-3.5" /> Add rule
      </button>
    </div>
  );
}

function AggregationRows() {
  const [rows, setRows] = useState([
    { field: "RequestedQuantity", agg: "Sum", by: "Month" },
  ]);
  return (
    <div className="flex flex-col gap-2">
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2">
          <Select value={r.field} onChange={(e) => setRows((x) => x.map((y, j) => (j === i ? { ...y, field: e.target.value } : y)))} className="h-8 w-52 font-mono text-[12.5px]">
            {SOURCE_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
          </Select>
          <Select value={r.agg} onChange={(e) => setRows((x) => x.map((y, j) => (j === i ? { ...y, agg: e.target.value } : y)))} className="h-8 w-32">
            {["Sum", "Count", "Average", "Min", "Max"].map((a) => <option key={a}>{a}</option>)}
          </Select>
          <span className="text-[12.5px] text-muted">grouped by</span>
          <Select value={r.by} onChange={(e) => setRows((x) => x.map((y, j) => (j === i ? { ...y, by: e.target.value } : y)))} className="h-8 w-32">
            {["Day", "Week", "Month", "Quarter", "Year"].map((a) => <option key={a}>{a}</option>)}
          </Select>
          <Button size="sm" variant="ghost" iconOnly aria-label="Remove" onClick={() => setRows((x) => x.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
        </div>
      ))}
      <button onClick={() => setRows((x) => [...x, { field: SOURCE_FIELDS[3], agg: "Sum", by: "Month" }])} className="inline-flex w-fit items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] font-medium text-accent-text transition-colors hover:bg-accent-tint">
        <Plus className="h-3.5 w-3.5" /> Add aggregation
      </button>
    </div>
  );
}

function ChecklistItem({ done, label }) {
  return (
    <div className="flex items-center gap-2">
      <CheckCircle2 className={done ? "h-4 w-4 text-match-fg" : "h-4 w-4 text-faint"} />
      <span className={done ? "text-[13px] text-text-secondary" : "text-[13px] text-muted"}>{label}</span>
    </div>
  );
}

/* ---- Manual tab ---------------------------------------------------------- */
function ManualFlow() {
  const [shadowApproved, setShadowApproved] = useState(false);
  const ref = useStagger([]);
  return (
    <div ref={ref} className="flex flex-col gap-5">
      <SectionCard index="A" title="Mapping sheet" description="Source of the field pairs and rules for this contract."
        status={<Badge status="match" dot>Parsed</Badge>}>
        <div className="flex flex-wrap items-center gap-3">
          <span className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-[13px]">
            <FileSpreadsheet className="h-4 w-4 text-muted" /> SOH_mapping_v3.xlsx
          </span>
          <Badge status="neutral">12 field pairs</Badge>
          <span className="text-[13px] text-muted">Identified:</span>
          <Badge status="info">SAP S/4HANA → SAP IBP</Badge>
        </div>
      </SectionCard>

      <SectionCard index="B" title="Business rules" description="Transformations, matching, and filters — expressed in plain language." icon={<ListChecks className="h-4 w-4" />}>
        <div className="flex flex-col gap-5">
          <RuleRows label="Transformations" hint="Reshape values before comparison (e.g. strip leading zeros)."
            initial={[{ field: "Material", text: "Remove leading zeros" }]} />
          <RuleRows label="Matching" hint="How rows are aligned across source and target."
            initial={[{ field: "ProductionPlant", text: "Map plant code to LOCID via prefix LOC-" }]} />
          <RuleRows label="Filters" hint="Restrict the rows entering the comparison."
            initial={[{ field: "RequestedDeliveryDate", text: "Only overlapping period" }]} />
        </div>
      </SectionCard>

      <SectionCard index="C" title="Aggregation" description="Roll up source rows to match the target's grain." icon={<Sigma className="h-4 w-4" />}>
        <AggregationRows />
      </SectionCard>

      <SectionCard index="D" title="Field mapping" description="Confirm source → target fields and which are keys vs compared.">
        <FieldMappingTable />
      </SectionCard>

      <SectionCard index="E" title="Transformation preview" description="Approve the transformed shadow dataset — you approve data, never code."
        icon={<Wand2 className="h-4 w-4" />}
        status={shadowApproved ? <Badge status="match" dot>Approved</Badge> : <Badge status="medium" dot>Needs approval</Badge>}>
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap gap-x-6 gap-y-2 rounded-lg border border-line bg-surface-2/50 px-4 py-3">
            <ChecklistItem done label="Contract compiled" />
            <ChecklistItem done label="Validated" />
            <ChecklistItem done label="Approved (contract_a1b2c3)" />
          </div>
          <BeforeAfter columns={SHADOW_COLUMNS} rows={SHADOW_ROWS} sourceCount={12480} shadowCount={9860} />
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2/40 px-4 py-3">
            <p className="text-[13px] text-muted">
              {shadowApproved ? "Shadow dataset approved — fingerprint pinned. You can run the reconciliation." : "Review the transformed rows, then approve to pin the shadow fingerprint."}
            </p>
            {shadowApproved ? (
              <Button variant="primary"><Play className="h-4 w-4" /> Run reconciliation</Button>
            ) : (
              <Button variant="secondary" onClick={() => setShadowApproved(true)}><ShieldCheck className="h-4 w-4" /> Approve shadow dataset</Button>
            )}
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

/* ---- Deterministic tab --------------------------------------------------- */
function DeterministicFlow() {
  const [ran, setRan] = useState(false);
  const ref = useStagger([]);
  return (
    <div ref={ref} className="flex flex-col gap-5">
      <SectionCard index="1" title="Field mapping" description="Keys and compared fields for the deterministic engine.">
        <FieldMappingTable />
      </SectionCard>

      <SectionCard index="2" title="Deterministic mapping" description="Rule-based value matching per entity — fully auditable, no shadow preview."
        icon={<Wand2 className="h-4 w-4" />}
        status={ran ? <Badge status="match" dot>Complete</Badge> : <Badge status="neutral">Not run</Badge>}
        actions={<Button size="sm" variant={ran ? "secondary" : "primary"} onClick={() => setRan(true)}><Wand2 className="h-4 w-4" /> {ran ? "Re-run mapping" : "Run deterministic mapping"}</Button>}>
        {!ran ? (
          <p className="text-[13px] text-muted">Run the deterministic mapping to resolve each source value against the target dimension using the rule ladder.</p>
        ) : (
          <div className="flex flex-col gap-5">
            <div>
              <div className="mb-2 flex items-center gap-2">
                <span className="text-[13px] font-medium text-text-secondary">Material → Product</span>
                <span className="font-mono text-[12px] text-muted">Material → PRDID</span>
              </div>
              <TierSummary counts={PRODUCT_TIER_COUNTS} />
            </div>
            <div>
              <div className="mb-2 flex items-center gap-2">
                <span className="text-[13px] font-medium text-text-secondary">Plant → Location</span>
                <span className="font-mono text-[12px] text-muted">ProductionPlant → LOCID</span>
              </div>
              <TierSummary counts={LOCATION_TIER_COUNTS} />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface-2/40 px-4 py-3">
              <p className="text-[13px] text-muted">Review each matched value and its rule + evidence before running the reconciliation.</p>
              <div className="flex items-center gap-2">
                <Button variant="secondary"><Eye className="h-4 w-4" /> View mapping review</Button>
                <Button variant="primary"><Play className="h-4 w-4" /> Run reconciliation</Button>
              </div>
            </div>
          </div>
        )}
      </SectionCard>
    </div>
  );
}

/* ---- Screen -------------------------------------------------------------- */
export function MappingScreen() {
  const [tab, setTab] = useState("manual");
  return (
    <div className="flex h-full flex-col">
      <StepHeader
        step={4}
        total={5}
        eyebrow="Mapping"
        title="Map source to target"
        description="Choose how source values are matched to the target dimension. Manual gives full control with a shadow preview; Deterministic applies an auditable rule ladder."
        actions={
          <>
            <Button variant="ghost"><ArrowLeft className="h-4 w-4" /> Back</Button>
            <Button variant="secondary">Continue <ArrowRight className="h-4 w-4" /></Button>
          </>
        }
      />
      <div className="flex flex-col gap-5 overflow-y-auto px-8 py-6">
        <div className="flex items-center justify-between">
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { value: "manual", label: "Manual Mapping", icon: <PencilRuler className="h-4 w-4" /> },
              { value: "deterministic", label: "Deterministic Mapping", icon: <Wand2 className="h-4 w-4" /> },
            ]}
          />
          <Tooltip content="Switching methods is lossless — each flow keeps its own state.">
            <span className="inline-flex items-center gap-1.5 text-[12px] text-muted"><Info className="h-3.5 w-3.5" /> Lossless switch</span>
          </Tooltip>
        </div>

        {tab === "manual" ? <ManualFlow /> : <DeterministicFlow />}
        <div className="h-6" />
      </div>
    </div>
  );
}

export default MappingScreen;
