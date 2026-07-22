import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "../../lib/utils";

export interface PaginationProps
  extends Omit<React.HTMLAttributes<HTMLElement>, "onChange"> {
  /** Current page (1-based). */
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  /** Pages shown on each side of the current page. Default 1. */
  siblingCount?: number;
}

const DOTS = "…";

/** Page navigation with first/last anchors and ellipsis collapsing. */
export const Pagination: React.FC<PaginationProps> = ({
  page,
  pageCount,
  onPageChange,
  siblingCount = 1,
  className,
  ...props
}) => {
  const pages = React.useMemo<(number | string)[]>(() => {
    if (pageCount <= 1) return [1];
    const start = Math.max(2, page - siblingCount);
    const end = Math.min(pageCount - 1, page + siblingCount);
    const result: (number | string)[] = [1];
    if (start > 2) result.push(DOTS);
    for (let i = start; i <= end; i++) result.push(i);
    if (end < pageCount - 1) result.push(DOTS);
    result.push(pageCount);
    return result;
  }, [page, pageCount, siblingCount]);

  if (pageCount <= 1) return null;

  const navBtn =
    "flex h-8 min-w-8 items-center justify-center rounded-[var(--bcone-radius-md)] px-2 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <nav
      aria-label="Pagination"
      className={cn("flex items-center gap-1", className)}
      {...props}
    >
      <button
        type="button"
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        aria-label="Previous page"
        className={cn(navBtn, "text-[var(--bcone-gray)] hover:bg-[var(--bcone-gray)]/10 hover:text-[var(--bcone-charcoal)]")}
      >
        <ChevronLeft className="h-4 w-4" />
      </button>

      {pages.map((p, i) =>
        typeof p === "number" ? (
          <button
            key={i}
            type="button"
            onClick={() => onPageChange(p)}
            aria-current={p === page ? "page" : undefined}
            className={cn(
              navBtn,
              "font-medium",
              p === page
                ? "bg-[var(--bcone-teal)] text-white"
                : "text-[var(--bcone-gray)] hover:bg-[var(--bcone-gray)]/10 hover:text-[var(--bcone-charcoal)]"
            )}
          >
            {p}
          </button>
        ) : (
          <span key={i} className="px-1.5 text-sm text-[var(--bcone-gray)]" aria-hidden="true">
            {p}
          </span>
        )
      )}

      <button
        type="button"
        onClick={() => onPageChange(page + 1)}
        disabled={page >= pageCount}
        aria-label="Next page"
        className={cn(navBtn, "text-[var(--bcone-gray)] hover:bg-[var(--bcone-gray)]/10 hover:text-[var(--bcone-charcoal)]")}
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </nav>
  );
};
Pagination.displayName = "Pagination";
