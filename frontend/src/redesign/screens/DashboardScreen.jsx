import { Plus, Activity, TriangleAlert, Database, Gauge } from "lucide-react";
import { Card, CardHeader, CardBody } from "../components/Card";
import { StatTile } from "../components/TierSummary";
import { DataTable } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { cn } from "../lib/cn";
import { useStagger } from "../lib/useGsap";
import { RECENT_RUNS, MATCH_TREND } from "../lib/sampleData";

function TrendChart({ data }) {
  const max = 100;
  return (
    <div className="flex h-32 items-end gap-3">
      {data.map((d) => (
        <div key={d.label} className="flex flex-1 flex-col items-center gap-2">
          <div className="flex w-full flex-1 items-end">
            <div className="w-full rounded-t-md bg-accent/80 transition-all hover:bg-accent" style={{ height: `${(d.value / max) * 100}%` }} title={`${d.value}%`} />
          </div>
          <span className="text-[11px] text-muted">{d.label}</span>
        </div>
      ))}
    </div>
  );
}

export function DashboardScreen({ onNewRun }) {
  const ref = useStagger([]);
  const columns = [
    { key: "id", header: "Contract", mono: true, width: "26%" },
    { key: "type", header: "Type" },
    { key: "pair", header: "Systems", render: (r) => <span className="font-mono text-[12px] text-muted">{r.pair}</span> },
    { key: "match", header: "Match rate", align: "right", render: (r) => (
      <span className={cn("font-medium tabular-nums", r.match >= 95 ? "text-match-fg" : r.match >= 85 ? "text-medium-fg" : "text-missing-fg")}>{r.match.toFixed(1)}%</span>
    ) },
    { key: "exceptions", header: "Exceptions", align: "right", render: (r) => r.exceptions.toLocaleString() },
    { key: "when", header: "When", render: (r) => <span className="text-muted">{r.when}</span> },
    { key: "status", header: "", render: (r) => <Badge status={r.status} dot>{r.status === "match" ? "Healthy" : r.status === "medium" ? "Watch" : "Critical"}</Badge> },
  ];
  return (
    <div className="flex h-full flex-col">
      <header className="sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-line bg-bg/80 px-8 py-5 backdrop-blur-md">
        <div>
          <h1 className="text-[22px] font-semibold tracking-[-0.015em]">Dashboard</h1>
          <p className="text-[13px] text-muted">Reconciliation health across your S/4HANA ↔ IBP contracts</p>
        </div>
        <Button variant="primary" onClick={onNewRun}><Plus className="h-4 w-4" /> New reconciliation</Button>
      </header>

      <div ref={ref} className="flex flex-col gap-6 overflow-y-auto px-8 py-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile status="match" value="95.0%" label="Avg match rate (7d)" />
          <StatTile status="info" value={12} label="Runs this week" />
          <StatTile status="missing" value={4152} label="Open exceptions" />
          <StatTile status="neutral" value={2} label="Connected systems" />
        </div>

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader icon={<Gauge className="h-4 w-4" />} title="Match rate · last 7 days" subtitle="Daily reconciled match percentage" />
            <CardBody><TrendChart data={MATCH_TREND} /></CardBody>
          </Card>
          <Card>
            <CardHeader icon={<Activity className="h-4 w-4" />} title="At a glance" />
            <CardBody className="flex flex-col gap-3">
              <Row icon={<Database className="h-4 w-4 text-accent-text" />} label="Datasets connected" value="S/4HANA · IBP" />
              <Row icon={<TriangleAlert className="h-4 w-4 text-medium-fg" />} label="Needs attention" value="1 contract" />
              <Row icon={<Activity className="h-4 w-4 text-match-fg" />} label="Last run" value="2h ago" />
            </CardBody>
          </Card>
        </div>

        <Card className="overflow-hidden">
          <CardHeader title="Recent reconciliations" subtitle="Latest contract runs" />
          <DataTable columns={columns} rows={RECENT_RUNS} className="rounded-none border-0" onRowClick={() => {}} />
        </Card>
      </div>
    </div>
  );
}

function Row({ icon, label, value }) {
  return (
    <div className="flex items-center justify-between">
      <span className="flex items-center gap-2 text-[13px] text-muted">{icon}{label}</span>
      <span className="text-[13px] font-medium text-text">{value}</span>
    </div>
  );
}

export default DashboardScreen;
