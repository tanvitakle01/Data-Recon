import { cn } from "../lib/cn";

/**
 * The workhorse data table.
 *
 * columns: [{
 *   key, header,
 *   align?: "left" | "right" | "center",
 *   mono?: boolean,          // technical identifier column -> JetBrains Mono
 *   width?: string,          // e.g. "160px" | "20%"
 *   headerClassName?, cellClassName?,
 *   render?: (row, i) => ReactNode
 * }]
 *
 * density: "comfortable" (default) | "compact" (4pt-tighter dense rows)
 * zebra: alternating row fill.  stickyHeader: header pinned on vertical scroll.
 */
export function DataTable({
  columns,
  rows,
  density = "comfortable",
  zebra = false,
  stickyHeader = true,
  getRowKey = (_, i) => i,
  onRowClick,
  rowClassName,
  className,
  emptyLabel = "No rows",
}) {
  const pad = density === "compact" ? "px-3 py-1.5" : "px-3.5 py-2.5";
  const headPad = density === "compact" ? "px-3 py-2" : "px-3.5 py-2.5";

  const alignCls = (a) => (a === "right" ? "text-right tabular-nums" : a === "center" ? "text-center" : "text-left");

  return (
    <div className={cn("overflow-auto rounded-xl border border-line bg-surface", className)}>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                style={{ width: col.width }}
                className={cn(
                  "z-10 border-b border-line bg-surface-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted",
                  headPad,
                  alignCls(col.align),
                  stickyHeader && "sticky top-0",
                  col.headerClassName
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-4 py-10 text-center text-[13px] text-muted">
                {emptyLabel}
              </td>
            </tr>
          )}
          {rows.map((row, i) => (
            <tr
              key={getRowKey(row, i)}
              onClick={onRowClick ? () => onRowClick(row, i) : undefined}
              className={cn(
                "border-b border-line/70 last:border-0 transition-colors",
                zebra && i % 2 === 1 && "bg-surface-2/40",
                onRowClick && "cursor-pointer hover:bg-accent-tint/40",
                typeof rowClassName === "function" ? rowClassName(row, i) : rowClassName
              )}
            >
              {columns.map((col) => {
                const content = col.render ? col.render(row, i) : row[col.key];
                return (
                  <td
                    key={col.key}
                    className={cn(
                      pad,
                      alignCls(col.align),
                      col.mono ? "font-mono text-[12.5px] text-text-secondary" : "text-text",
                      col.cellClassName
                    )}
                  >
                    {content}
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

export default DataTable;
