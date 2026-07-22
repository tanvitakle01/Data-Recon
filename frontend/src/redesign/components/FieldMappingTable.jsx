import { useState } from "react";
import { KeyRound, BarChart3, RefreshCw } from "lucide-react";
import { DataTable } from "./DataTable";
import { Select } from "./Select";
import { SegmentedControl } from "./SegmentedControl";
import { Button } from "./Button";
import { TARGET_FIELD_OPTIONS, DEFAULT_MAPPING } from "../lib/sampleData";

/**
 * Editable field-mapping table: Logical Field (human) | Source Field (mono) |
 * Target Field (mono select) | Mapping Type (Key vs Compare).
 */
export function FieldMappingTable({ initial = DEFAULT_MAPPING, onRegenerate }) {
  const [rows, setRows] = useState(initial);
  const setRow = (i, patch) => setRows((r) => r.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));

  const columns = [
    { key: "logical", header: "Logical Field", width: "24%", render: (r) => <span className="font-medium text-text">{r.logical}</span> },
    { key: "source", header: "Source Field", mono: true, width: "24%" },
    {
      key: "target",
      header: "Target Field",
      width: "28%",
      render: (r, i) => (
        <Select value={r.target} onChange={(e) => setRow(i, { target: e.target.value })} className="h-8 font-mono text-[12.5px]">
          {TARGET_FIELD_OPTIONS.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
          {r.target === "—" && <option value="—">—</option>}
        </Select>
      ),
    },
    {
      key: "type",
      header: "Mapping Type",
      render: (r, i) => (
        <SegmentedControl
          size="sm"
          accentActive
          value={r.type}
          onChange={(v) => setRow(i, { type: v })}
          options={[
            { value: "key", label: "Key", icon: <KeyRound className="h-3.5 w-3.5" /> },
            { value: "compare", label: "Compare", icon: <BarChart3 className="h-3.5 w-3.5" /> },
          ]}
        />
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-[13px] text-muted">
          {rows.filter((r) => r.type === "key").length} key · {rows.filter((r) => r.type === "compare").length} compare
        </p>
        <Button size="sm" variant="secondary" onClick={onRegenerate}>
          <RefreshCw className="h-3.5 w-3.5" /> Regenerate auto-mapping
        </Button>
      </div>
      <DataTable columns={columns} rows={rows} />
    </div>
  );
}

export default FieldMappingTable;
