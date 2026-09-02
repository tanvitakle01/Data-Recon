import { useState } from "react";
import { ArrowRight, Download, RefreshCw, Plus, Search, Trash2, Database, Library } from "lucide-react";
import { Button } from "../components/Button";
import { Badge, TierBadge, OutcomeBadge, ChangeBadge } from "../components/Badge";
import { Card, CardHeader, CardBody, CardFooter } from "../components/Card";
import { Field, Input, Textarea } from "../components/Input";
import { Select } from "../components/Select";
import { Toggle, Checkbox } from "../components/Toggle";
import { Tabs } from "../components/Tabs";
import { Tooltip } from "../components/Tooltip";
import { EmptyState } from "../components/EmptyState";
import { DataTable } from "../components/DataTable";
import { Stepper } from "../components/Stepper";
import { useStagger } from "../lib/useGsap";

function Section({ title, description, children }) {
  return (
    <section data-animate className="flex flex-col gap-4">
      <div>
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">{title}</h2>
        {description && <p className="mt-0.5 text-[13px] text-muted">{description}</p>}
      </div>
      {children}
    </section>
  );
}

const STATUSES = ["match", "high", "medium", "mismatch", "missing", "scope", "extra", "info", "neutral"];

const TABLE_ROWS = [
  { src: "000000004711", tgt: "PRD-4711", tier: "very_high", rule: "product.rule2_exact_id", qty: 1240 },
  { src: "000000008120", tgt: "PRD-8120", tier: "high", rule: "product.rule3_normalized_identity", qty: 860 },
  { src: "MAT-COATING-02", tgt: "PRD-COAT2", tier: "medium", rule: "product.rule5_description_match", qty: 45 },
  { src: "0000LEGACY99", tgt: "—", tier: "none", rule: "product.rule6_no_match", qty: 0 },
  { src: "SAMPLE-KIT-X", tgt: "n/a", tier: "out_of_scope", rule: "product.rule0_group_out_of_scope", qty: 12 },
];

export function ComponentGallery() {
  const [tab, setTab] = useState("manual");
  const [pill, setPill] = useState("all");
  const [toggle, setToggle] = useState(true);
  const [check, setCheck] = useState(true);
  const [density, setDensity] = useState("comfortable");
  const [zebra, setZebra] = useState(false);
  const ref = useStagger([]);

  const columns = [
    { key: "src", header: "Source Value", mono: true, width: "22%" },
    { key: "tgt", header: "Matched Target Value", mono: true, width: "20%" },
    { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.tier} /> },
    { key: "rule", header: "Rule", mono: true },
    { key: "qty", header: "Qty", align: "right", render: (r) => r.qty.toLocaleString() },
  ];

  return (
    <div className="flex flex-col h-full">
      <header className="sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-line bg-bg/80 px-8 py-4 backdrop-blur">
        <div>
          <h1 className="text-[22px] font-semibold tracking-[-0.015em]">Component Library</h1>
          <p className="text-[13px] text-muted">Step 3 · assembled from the Step 2 tokens · try the theme toggle in the sidebar</p>
        </div>
        <Badge status="info" dot>Preview build</Badge>
      </header>

      <div ref={ref} className="flex flex-col gap-10 overflow-y-auto px-8 py-8">
        {/* Buttons */}
        <Section title="Buttons" description="primary · secondary · ghost · destructive — sizes sm / md / lg">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary">Run reconciliation</Button>
            <Button variant="secondary">Cancel</Button>
            <Button variant="ghost">Change method</Button>
            <Button variant="destructive"><Trash2 className="h-4 w-4" /> Reset</Button>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" variant="secondary"><RefreshCw className="h-3.5 w-3.5" /> Regenerate</Button>
            <Button size="md" variant="primary">Continue <ArrowRight className="h-4 w-4" /></Button>
            <Button size="lg" variant="primary"><Download className="h-[18px] w-[18px]" /> Download sheet</Button>
            <Button size="md" variant="secondary" iconOnly aria-label="Add"><Plus className="h-4 w-4" /></Button>
          </div>
        </Section>

        {/* Badges */}
        <Section title="Semantic badges" description="the 8 status meanings — soft and solid — plus neutral. Same tokens on every screen.">
          <div className="flex flex-wrap gap-2.5">
            {STATUSES.map((s) => (
              <Badge key={s} status={s} dot>{s}</Badge>
            ))}
          </div>
          <div className="flex flex-wrap gap-2.5">
            {STATUSES.map((s) => (
              <Badge key={s} status={s} emphasis="solid">{s}</Badge>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <TierBadge tier="very_high" /><TierBadge tier="high" /><TierBadge tier="medium" />
            <TierBadge tier="none" /><TierBadge tier="out_of_scope" />
            <span className="mx-2 h-4 w-px bg-line-2" />
            <OutcomeBadge outcome="match" /><OutcomeBadge outcome="mismatch" /><OutcomeBadge outcome="missing_in_target" /><OutcomeBadge outcome="extra_in_target" />
            <span className="mx-2 h-4 w-px bg-line-2" />
            <ChangeBadge change="added" /><ChangeBadge change="modified" /><ChangeBadge change="removed" /><ChangeBadge change="aggregated" />
          </div>
        </Section>

        {/* Form controls */}
        <Section title="Form controls">
          <div className="grid max-w-3xl grid-cols-1 gap-5 md:grid-cols-2">
            <Field label="Comparison type" htmlFor="ct">
              <Select id="ct" defaultValue="soh"><option value="soh">Sales Order History</option></Select>
            </Field>
            <Field label="Contract ID" hint="Technical identifier — mono face" htmlFor="cid">
              <Input id="cid" mono defaultValue="contract_a1b2c3d4e5f6" />
            </Field>
            <Field label="Target field" htmlFor="tf">
              <Input id="tf" mono placeholder="PRDID" />
            </Field>
            <Field label="Search" htmlFor="sr">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <Input id="sr" className="pl-9" placeholder="Search values…" />
              </div>
            </Field>
            <Field label="Rule note" className="md:col-span-2" htmlFor="rn">
              <Textarea id="rn" placeholder="Describe a transformation rule in plain language…" />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-6">
            <Toggle checked={toggle} onChange={setToggle} label="Overlapping period only" />
            <Checkbox checked={check} onChange={setCheck} label="Include supporting fields" />
          </div>
        </Section>

        {/* Tabs */}
        <Section title="Tabs — the Manual / Deterministic fork">
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { value: "manual", label: "Manual Mapping" },
              { value: "deterministic", label: "Deterministic Mapping" },
            ]}
          />
          <div className="pt-1">
            <Tabs
              variant="pill"
              value={pill}
              onChange={setPill}
              items={[
                { value: "all", label: "All" },
                { value: "very_high", label: "VERY_HIGH" },
                { value: "high", label: "HIGH" },
                { value: "none", label: "Unmapped" },
                { value: "oos", label: "Excluded" },
              ]}
            />
          </div>
        </Section>

        {/* Cards + empty + tooltip */}
        <Section title="Cards, empty state, tooltips">
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader
                icon={<Database className="h-4 w-4" />}
                title="SAP S/4HANA · Source"
                subtitle="A_SalesOrderItem · 12,480 rows"
                actions={<Tooltip content="Replace dataset"><Button size="sm" variant="ghost" iconOnly aria-label="More"><RefreshCw className="h-4 w-4" /></Button></Tooltip>}
              />
              <CardBody>
                <div className="flex flex-wrap gap-2">
                  <Badge status="neutral">6 compare fields</Badge>
                  <Badge status="info">3 supporting</Badge>
                  <Badge status="match" dot>Ready</Badge>
                </div>
              </CardBody>
              <CardFooter>
                <Button size="sm" variant="secondary">Preview</Button>
                <Button size="sm" variant="ghost">Edit fields</Button>
              </CardFooter>
            </Card>
            <EmptyState
              icon={<Library className="h-5 w-5" />}
              title="No stored mappings yet"
              description="Approved value mappings will appear here once you run a deterministic mapping."
              action={<Button size="sm" variant="primary">Run deterministic mapping</Button>}
            />
          </div>
        </Section>

        {/* Data table */}
        <Section title="Data table — the workhorse" description="sticky header · mono identifier columns · right-aligned numerics · tier badges">
          <div className="flex items-center gap-6">
            <Tabs
              variant="pill"
              value={density}
              onChange={setDensity}
              items={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]}
            />
            <Toggle checked={zebra} onChange={setZebra} label="Zebra rows" />
          </div>
          <DataTable columns={columns} rows={TABLE_ROWS} density={density} zebra={zebra} className="max-h-[320px]" />
        </Section>

        {/* Stepper */}
        <Section title="Wizard stepper">
          <Card className="max-w-xs">
            <CardBody>
              <Stepper
                steps={[
                  { key: "type", label: "Type", caption: "Sales Order History", status: "complete" },
                  { key: "source", label: "Source", caption: "SAP S/4HANA", status: "complete" },
                  { key: "target", label: "Target", caption: "SAP IBP", status: "complete" },
                  { key: "mapping", label: "Mapping", caption: "Deterministic", status: "current" },
                  { key: "results", label: "Results", status: "locked" },
                ]}
                onStepClick={() => {}}
              />
            </CardBody>
          </Card>
        </Section>

        <div className="h-4" />
      </div>
    </div>
  );
}

export default ComponentGallery;
