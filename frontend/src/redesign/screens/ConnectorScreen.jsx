import { useState } from "react";
import { ArrowRight, ArrowLeft, UploadCloud, Radio, Database, FileSpreadsheet, RefreshCw, Table2 } from "lucide-react";
import { StepHeader } from "../components/StepHeader";
import { SectionCard } from "../components/SectionCard";
import { ChoiceCard } from "../components/ChoiceCard";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { DataTable } from "../components/DataTable";
import { useStagger } from "../lib/useGsap";

const ROLE_META = {
  source: { step: 2, label: "Source", system: "SAP S/4HANA", entity: "A_SalesOrderItem", rows: 12480,
    columns: ["Material", "ProductionPlant", "RequestedDeliveryDate", "RequestedQuantity", "SalesOrderItemText"],
    preview: [
      { Material: "000000004711", ProductionPlant: "1010", RequestedDeliveryDate: "2026-03-14", RequestedQuantity: "620", SalesOrderItemText: "Bearing, 20mm" },
      { Material: "000000008120", ProductionPlant: "1010", RequestedDeliveryDate: "2026-03-22", RequestedQuantity: "860", SalesOrderItemText: "Gearbox std" },
      { Material: "MAT-COAT-02", ProductionPlant: "2020", RequestedDeliveryDate: "2026-04-02", RequestedQuantity: "45", SalesOrderItemText: "Coating, blue" },
    ] },
  target: { step: 3, label: "Target", system: "SAP IBP", entity: "PLANNING_DATA_API_SRV", rows: 9860,
    columns: ["PRDID", "LOCID", "PERIODID0_TSTAMP", "SALESORDERREQUEST"],
    preview: [
      { PRDID: "PRD-4711", LOCID: "LOC-1010", PERIODID0_TSTAMP: "2026-03", SALESORDERREQUEST: "1,240" },
      { PRDID: "PRD-8120", LOCID: "LOC-1010", PERIODID0_TSTAMP: "2026-03", SALESORDERREQUEST: "900" },
      { PRDID: "PRD-COAT2", LOCID: "LOC-2020", PERIODID0_TSTAMP: "2026-04", SALESORDERREQUEST: "45" },
    ] },
};

export function ConnectorScreen({ role = "source", onContinue, onBack }) {
  const m = ROLE_META[role];
  const [mode, setMode] = useState("live"); // 'excel' | 'live'
  const ref = useStagger([role]);

  const columns = m.columns.map((c) => ({
    key: c, header: c, mono: true,
    align: c === "RequestedQuantity" || c === "SALESORDERREQUEST" ? "right" : "left",
  }));

  return (
    <div className="flex h-full flex-col">
      <StepHeader
        step={m.step} total={5} eyebrow={m.label}
        title={`Choose the ${m.label.toLowerCase()} dataset`}
        description={`Upload an Excel/CSV extract, or fetch live from ${m.system} using discovered metadata.`}
        actions={
          <>
            <Button variant="ghost" onClick={onBack}><ArrowLeft className="h-4 w-4" /> Back</Button>
            <Button variant="secondary" onClick={onContinue}>Continue <ArrowRight className="h-4 w-4" /></Button>
          </>
        }
      />
      <div ref={ref} className="flex flex-col gap-5 overflow-y-auto px-8 py-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <ChoiceCard
            icon={<UploadCloud className="h-5 w-5" />}
            title="Excel / CSV upload"
            description="Bring a static extract. We parse the sheet and preview it before mapping."
            selected={mode === "excel"} onClick={() => setMode("excel")}
          />
          <ChoiceCard
            icon={<Radio className="h-5 w-5" />}
            title="Live fetch"
            description={`Query ${m.system} directly via OData. Metadata-driven field selection.`}
            recommended selected={mode === "live"} onClick={() => setMode("live")}
          />
        </div>

        <SectionCard
          icon={mode === "excel" ? <FileSpreadsheet className="h-4 w-4" /> : <Database className="h-4 w-4" />}
          title={mode === "excel" ? "Uploaded dataset" : `${m.system} · ${m.entity}`}
          description={mode === "excel" ? "SOH_extract.xlsx" : "Live fetch · overlapping period"}
          status={<Badge status="match" dot>Loaded</Badge>}
          actions={<Button size="sm" variant="ghost">{mode === "excel" ? <><RefreshCw className="h-4 w-4" /> Replace file</> : <><Table2 className="h-4 w-4" /> Edit fields</>}</Button>}
        >
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
              <Badge status="neutral">{m.rows.toLocaleString()} rows</Badge>
              <Badge status="neutral">{m.columns.length} columns</Badge>
              <Badge status="info">{mode === "excel" ? "Excel" : "OData"}</Badge>
            </div>
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">Preview</p>
              <DataTable columns={columns} rows={m.preview} density="compact" zebra />
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

export default ConnectorScreen;
