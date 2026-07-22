import * as React from "react";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import { cn } from "../../lib/utils";

export interface Column<T> {
  key: keyof T;
  header: string;
  sortable?: boolean;
  render?: (value: T[keyof T], row: T) => React.ReactNode;
  className?: string;
}

export interface DataTableProps<T extends { id: string | number }> {
  columns: Column<T>[];
  data: T[];
  pageSize?: number;
  className?: string;
  emptyMessage?: string;
  /** Opt-in multi-row selection: renders a leading checkbox column. */
  selectable?: boolean;
  /** Controlled set of selected row ids (parent-owned). */
  selectedIds?: Set<string | number>;
  /** Called with the next selection when a row checkbox or select-all toggles. */
  onSelectionChange?: (ids: Set<string | number>) => void;
}

type SortDir = "asc" | "desc" | null;

const EMPTY_SELECTION: Set<string | number> = new Set();

/** Checkbox that supports the tri-state (indeterminate) header. */
function SelectCheckbox({
  checked,
  indeterminate,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  indeterminate?: boolean;
  onChange: () => void;
  ariaLabel: string;
}) {
  const ref = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    if (ref.current) ref.current.indeterminate = Boolean(indeterminate);
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onChange={onChange}
      onClick={(e) => e.stopPropagation()}
      aria-label={ariaLabel}
      className="h-4 w-4 cursor-pointer accent-[var(--bcone-teal)]"
    />
  );
}

export function DataTable<T extends { id: string | number }>({
  columns,
  data,
  pageSize = 10,
  className,
  emptyMessage = "No results.",
  selectable = false,
  selectedIds,
  onSelectionChange,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = React.useState<keyof T | null>(null);
  const [sortDir, setSortDir] = React.useState<SortDir>(null);
  const [page, setPage] = React.useState(1);

  const handleSort = (key: keyof T) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : d === "desc" ? null : "asc"));
      if (sortDir === "desc") setSortKey(null);
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const sorted = React.useMemo(() => {
    if (!sortKey || !sortDir) return data;
    return [...data].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [data, sortKey, sortDir]);

  const totalPages = Math.ceil(sorted.length / pageSize);
  const paged = sorted.slice((page - 1) * pageSize, page * pageSize);

  // ── selection (opt-in) — select-all spans every row across all pages ──────
  const selected = selectedIds ?? EMPTY_SELECTION;
  const allIds = data.map((r) => r.id);
  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id));
  const someSelected = !allSelected && allIds.some((id) => selected.has(id));
  const toggleAll = () =>
    onSelectionChange?.(allSelected ? new Set() : new Set(allIds));
  const toggleOne = (id: string | number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelectionChange?.(next);
  };

  const SortIcon = ({ col }: { col: Column<T> }) => {
    if (!col.sortable) return null;
    if (sortKey !== col.key) return <ChevronsUpDown className="h-3.5 w-3.5 text-[var(--bcone-gray)]" />;
    return sortDir === "asc"
      ? <ChevronUp className="h-3.5 w-3.5 text-[var(--bcone-teal)]" />
      : <ChevronDown className="h-3.5 w-3.5 text-[var(--bcone-teal)]" />;
  };

  return (
    <div className={cn("w-full", className)}>
      <div className="overflow-x-auto rounded-[var(--bcone-radius-md)] border border-[var(--bcone-gray)]/20 shadow-[var(--bcone-shadow-sm)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--bcone-charcoal)]/5 border-b border-[var(--bcone-gray)]/20">
            <tr>
              {selectable && (
                <th className="w-10 px-4 py-3">
                  <SelectCheckbox
                    checked={allSelected}
                    indeterminate={someSelected}
                    onChange={toggleAll}
                    ariaLabel="Select all rows"
                  />
                </th>
              )}
              {columns.map((col) => (
                <th
                  key={String(col.key)}
                  className={cn(
                    "px-4 py-3 text-left text-xs font-black text-[var(--bcone-charcoal)] uppercase tracking-wider",
                    col.sortable && "cursor-pointer select-none hover:text-[var(--bcone-teal)]",
                    col.className
                  )}
                  onClick={col.sortable ? () => handleSort(col.key) : undefined}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.header}
                    <SortIcon col={col} />
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--bcone-gray)]/10">
            {paged.length === 0 ? (
              <tr>
                <td colSpan={columns.length + (selectable ? 1 : 0)} className="px-4 py-8 text-center text-[var(--bcone-gray)]">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              paged.map((row) => (
                <tr
                  key={row.id}
                  className={cn(
                    "transition-colors",
                    selected.has(row.id)
                      ? "bg-[var(--bcone-teal)]/10"
                      : "hover:bg-[var(--bcone-teal)]/5"
                  )}
                >
                  {selectable && (
                    <td className="w-10 px-4 py-3">
                      <SelectCheckbox
                        checked={selected.has(row.id)}
                        onChange={() => toggleOne(row.id)}
                        ariaLabel="Select row"
                      />
                    </td>
                  )}
                  {columns.map((col) => (
                    <td key={String(col.key)} className={cn("px-4 py-3 text-[var(--bcone-charcoal)]", col.className)}>
                      {col.render ? col.render(row[col.key], row) : String(row[col.key] ?? "")}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 text-sm text-[var(--bcone-gray)]">
          <span>
            {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, sorted.length)} of {sorted.length}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 rounded border border-[var(--bcone-gray)]/30 hover:border-[var(--bcone-teal)] disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-3 py-1 rounded border border-[var(--bcone-gray)]/30 hover:border-[var(--bcone-teal)] disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
