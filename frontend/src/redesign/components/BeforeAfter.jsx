import { ArrowRight } from "lucide-react";
import { cn } from "../lib/cn";
import { CHANGE, STATUS_CLASSES } from "../lib/status";

const LEGEND = ["added", "modified", "removed", "aggregated"];

function MiniTable({ columns, rows, side }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={cn(
                  "border-b border-line bg-surface-2 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted",
                  c.align === "right" ? "text-right" : "text-left",
                  c.mono && "font-mono normal-case tracking-normal"
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-line/70 last:border-0">
              {columns.map((c) => {
                const cell = row[side][c.key];
                const change = side === "after" ? row.changes?.[c.key] : undefined;
                const cc = change ? STATUS_CLASSES[CHANGE[change].status] : null;
                return (
                  <td
                    key={c.key}
                    className={cn(
                      "px-3 py-2",
                      c.align === "right" ? "text-right tabular-nums" : "text-left",
                      c.mono ? "font-mono text-[12.5px]" : "text-text",
                      cc ? cn(cc.bg, cc.fg, "font-medium") : "text-text-secondary"
                    )}
                  >
                    {cell}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BeforeAfter({ columns, rows, sourceCount, shadowCount, className }) {
  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">Change legend</span>
        {LEGEND.map((k) => {
          const cc = STATUS_CLASSES[CHANGE[k].status];
          return (
            <span key={k} className="inline-flex items-center gap-1.5 text-[12px] text-text-secondary">
              <span className={cn("h-2.5 w-2.5 rounded-sm", cc.solid)} />
              {CHANGE[k].label}
            </span>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto_1fr] lg:items-center">
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-[12px] font-medium text-text-secondary">Original Source</span>
            {sourceCount != null && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-muted tabular-nums">{sourceCount.toLocaleString()} rows</span>}
          </div>
          <MiniTable columns={columns} rows={rows} side="before" />
        </div>

        <div className="mx-auto hidden h-8 w-8 items-center justify-center rounded-full border border-line bg-surface text-accent shadow-e1 lg:flex">
          <ArrowRight className="h-4 w-4" />
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-[12px] font-medium text-accent-text">Shadow Source · Transformed</span>
            {shadowCount != null && <span className="rounded-full bg-accent-tint px-2 py-0.5 text-[11px] font-medium text-accent-text tabular-nums">{shadowCount.toLocaleString()} rows</span>}
          </div>
          <MiniTable columns={columns} rows={rows} side="after" />
        </div>
      </div>
    </div>
  );
}

export default BeforeAfter;
