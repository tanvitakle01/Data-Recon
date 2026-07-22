import { ArrowRight, UploadCloud, FileSpreadsheet, Database, CheckCircle2 } from "lucide-react";
import { StepHeader } from "../components/StepHeader";
import { SectionCard } from "../components/SectionCard";
import { Field } from "../components/Input";
import { Select } from "../components/Select";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { useStagger } from "../lib/useGsap";

function IdentifiedSide({ role, system, entity, confidence, evidence }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">{role}</span>
        <Badge status="match" dot>{confidence}</Badge>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <Database className="h-4 w-4 text-accent-text" />
        <span className="text-[15px] font-semibold text-text">{system}</span>
      </div>
      <p className="mt-1 font-mono text-[12px] text-muted">{entity}</p>
      <p className="mt-2 text-[12.5px] leading-relaxed text-text-secondary">{evidence}</p>
    </Card>
  );
}

export function TypeScreen({ onContinue }) {
  const ref = useStagger([]);
  return (
    <div className="flex h-full flex-col">
      <StepHeader
        step={1} total={5} eyebrow="Type"
        title="What are you comparing?"
        description="Pick the comparison type. Optionally upload a mapping sheet and we'll identify the source and target systems for you."
        actions={<Button variant="secondary" onClick={onContinue}>Continue <ArrowRight className="h-4 w-4" /></Button>}
      />
      <div ref={ref} className="flex max-w-4xl flex-col gap-5 overflow-y-auto px-8 py-6">
        <SectionCard index="1" title="Comparison type">
          <Field label="Type" htmlFor="ctype" hint="Additional comparison types are added as connectors are certified.">
            <Select id="ctype" defaultValue="soh" className="max-w-sm">
              <option value="soh">Sales Order History</option>
            </Select>
          </Field>
        </SectionCard>

        <SectionCard index="2" title="Mapping sheet" description="Optional — accelerates the wizard by pre-selecting systems and fields."
          status={<Badge status="match" dot>Parsed</Badge>}>
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between rounded-xl border border-dashed border-line-2 bg-surface-2/40 px-4 py-3">
              <span className="inline-flex items-center gap-2 text-[13px] text-text-secondary">
                <FileSpreadsheet className="h-4 w-4 text-muted" /> SOH_mapping_v3.xlsx · 12 field pairs
              </span>
              <Button size="sm" variant="ghost"><UploadCloud className="h-4 w-4" /> Replace</Button>
            </div>
            <div className="flex items-center gap-2 text-[13px] text-text-secondary">
              <CheckCircle2 className="h-4 w-4 text-match-fg" /> Systems identified from the sheet
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <IdentifiedSide role="Source" system="SAP S/4HANA" entity="A_SalesOrderItem"
                confidence="High" evidence="Columns reference VBAP-MATNR, VBAP-WERKS and VBEP-EDATU — table-qualified S/4 fields." />
              <IdentifiedSide role="Target" system="SAP IBP" entity="PLANNING_DATA_API_SRV"
                confidence="High" evidence="Target keys PRDID, LOCID and key figure SALESORDERREQUEST match the IBP planning model." />
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

export default TypeScreen;
