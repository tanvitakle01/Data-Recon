import * as React from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "../../lib/utils";

export interface BreadcrumbItem {
  label: React.ReactNode;
  href?: string;
  onClick?: (e: React.MouseEvent) => void;
}

export interface BreadcrumbsProps extends React.HTMLAttributes<HTMLElement> {
  items: BreadcrumbItem[];
  /** Custom separator node. Defaults to a chevron. */
  separator?: React.ReactNode;
}

/** Navigation trail. The last item is rendered as the current (non-link) page. */
export const Breadcrumbs: React.FC<BreadcrumbsProps> = ({
  items,
  separator,
  className,
  ...props
}) => (
  <nav
    aria-label="Breadcrumb"
    className={cn("flex flex-wrap items-center gap-1.5 text-sm", className)}
    {...props}
  >
    {items.map((item, i) => {
      const last = i === items.length - 1;
      const interactive = !last && (item.href !== undefined || item.onClick !== undefined);
      return (
        <React.Fragment key={i}>
          {interactive ? (
            <a
              href={item.href ?? "#"}
              onClick={item.onClick}
              className="text-[var(--bcone-gray)] transition-colors hover:text-[var(--bcone-teal)]"
            >
              {item.label}
            </a>
          ) : (
            <span
              aria-current={last ? "page" : undefined}
              className={
                last
                  ? "font-bold text-[var(--bcone-charcoal)]"
                  : "text-[var(--bcone-gray)]"
              }
            >
              {item.label}
            </span>
          )}
          {!last && (
            <span className="text-[var(--bcone-gray)]/50" aria-hidden="true">
              {separator ?? <ChevronRight className="h-3.5 w-3.5" />}
            </span>
          )}
        </React.Fragment>
      );
    })}
  </nav>
);
Breadcrumbs.displayName = "Breadcrumbs";
