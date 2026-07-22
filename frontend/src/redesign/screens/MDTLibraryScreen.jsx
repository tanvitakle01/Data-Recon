import { useState } from "react";
import { Database, Boxes, MapPin, Search, ShieldCheck } from "lucide-react";
import { StepHeader } from "../components/StepHeader";
import { Card } from "../components/Card";
import { Badge, TierBadge } from "../components/Badge";
import { DataTable } from "../components/DataTable";
import { StatTile } from "../components/TierSummary";
import { Input } from "../components/Input";
import { cn } from "../lib/cn";
import { useStagger } from "../lib/useGsap";
import { MDT_GROUPS, AUX_STATUS, AUX_RULE } from "../lib/sampleData";

function FillBar({ value }) {
  if (value == null) return <span className="text-[12px] text-faint">—</span>;
  const status = value >= 80 ? "match" : value >= 40 ? "medium" : "missing";
  const color = { match: "bg-match-solid", medium: "bg-medium-solid", missing: "bg-missing-solid" }[status];
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-3">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${value}%` }} />
      </div>
      <span className="w-8 text-right text-[12px] tabular-nums text-muted">{value}%</span>
    </div>
  );
}

export function MDTLibraryScreen() {
  const [sel, setSel] = useState(MDT_GROUPS[0].key);
  const [q, setQ] = useState("");
  const ref = useStagger([sel]);
  const group = MDT_GROUPS.find((g) => g.key === sel);
  const rows = group.rows.filter((r) => r.attr.toLowerCase().includes(q.toLowerCase()));

  const confirmed = group.rows.filter((r) => r.status === "confirmed").length;
  const empty = group.rows.filter((r) => r.status === "empty").length;
  const absent = group.rows.filter((r) => r.status === "absent").length;

  const columns = [
    { key: "attr", header: "Attribute", mono: true, width: "26%" },
    { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.tier} dot={false} /> },
    { key: "status", header: "Status", render: (r) => <Badge status={AUX_STATUS[r.status].status} dot>{AUX_STATUS[r.status].label}</Badge> },
    { key: "fill", header: "Fill rate", render: (r) => <FillBar value={r.fill} /> },
    { key: "rule", header: "Used by a rule?", render: (r) => <Badge status={AUX_RULE[r.rule].status}>{AUX_RULE[r.rule].label}</Badge> },
  ];

  return (
    <div className="flex h-full flex-col">
      <StepHeader
        eyebrow="Knowledge"
        title="MDT Library"
        description="Stored auxiliary-field knowledge used as matching evidence — never in business keys, compare fields, or output. Browse by connector."
        actions={<Badge status="scope">Evidence only</Badge>}
      />
      <div className="flex min-h-0 flex-1">
        {/* connector rail */}
        <div className="w-64 shrink-0 border-r border-line p-3">
          <p className="px-2 pb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">Connectors</p>
          <div className="flex flex-col gap-1">
            {MDT_GROUPS.map((g) => {
              const active = g.key === sel;
              const Icon = g.key.includes("location") || g.key.includes("plant") ? MapPin : Boxes;
              return (
                <button key={g.key} onClick={() => setSel(g.key)}
                  className={cn("flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors",
                    active ? "bg-accent-tint" : "hover:bg-surface-2")}>
                  <Icon className={cn("mt-0.5 h-4 w-4", active ? "text-accent-text" : "text-muted")} />
                  <div className="min-w-0">
                    <p className={cn("text-[13px] font-medium", active ? "text-accent-text" : "text-text")}>{g.label}</p>
                    <p className="flex items-center gap-1 text-[11px] text-muted"><Database className="h-3 w-3" /> {g.system}</p>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* detail */}
        <div ref={ref} className="flex min-w-0 flex-1 flex-col gap-5 overflow-y-auto p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-[16px] font-semibold text-text">{group.label}</h2>
              <p className="font-mono text-[12px] text-muted">root · {group.root}</p>
            </div>
            <div className="relative w-64">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" placeholder="Search attributes…" />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <StatTile status="match" value={confirmed} label="Confirmed" />
            <StatTile status="medium" value={empty} label="Empty (0% filled)" />
            <StatTile status="missing" value={absent} label="Absent" />
          </div>

          <Card className="overflow-hidden">
            <div className="flex items-center gap-2 border-b border-line px-5 py-3">
              <ShieldCheck className="h-4 w-4 text-accent-text" />
              <span className="text-[13px] font-medium text-text">Auxiliary attributes</span>
            </div>
            <DataTable columns={columns} rows={rows} className="rounded-none border-0" emptyLabel="No matching attributes" />
          </Card>
        </div>
      </div>
    </div>
  );
}

export default MDTLibraryScreen;
