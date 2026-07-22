import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "../../lib/utils";

export interface SidebarItem {
  label: string;
  icon?: React.ReactNode;
  href?: string;
  onClick?: () => void;
  active?: boolean;
  badge?: string | number;
}

export interface SidebarSection {
  title?: string;
  items: SidebarItem[];
}

export interface SidebarProps {
  sections: SidebarSection[];
  logo?: React.ReactNode;
  collapsed?: boolean;
  onToggle?: () => void;
  className?: string;
  footer?: React.ReactNode;
}

export const Sidebar: React.FC<SidebarProps> = ({
  sections,
  logo,
  collapsed = false,
  onToggle,
  className,
  footer,
}) => {
  return (
    <aside
      className={cn(
        "flex flex-col h-screen bg-[var(--bcone-black)] text-white transition-all duration-200 border-r border-white/10",
        collapsed ? "w-16" : "w-60",
        className
      )}
    >
      {/* Logo area — the collapse/expand toggle always lives here so open and
          close are in the same spot. */}
      <div className={cn(
        "flex items-center h-16 border-b border-white/10",
        collapsed ? "justify-center px-2" : "gap-3 px-4"
      )}>
        {collapsed ? (
          onToggle ? (
            <button
              onClick={onToggle}
              title="Expand sidebar"
              aria-label="Expand sidebar"
              className="flex items-center justify-center h-9 w-9 rounded-[var(--bcone-radius-sm)] text-white/70 hover:bg-white/10 hover:text-white transition-colors"
            >
              <ChevronRight className="h-5 w-5" />
            </button>
          ) : (
            logo && <div className="flex-shrink-0">{logo}</div>
          )
        ) : (
          <>
            {logo && <div className="flex-shrink-0">{logo}</div>}
            <span className="text-sm font-black text-white truncate">
              Bristlecone AI
            </span>
            {onToggle && (
              <button
                onClick={onToggle}
                title="Collapse sidebar"
                aria-label="Collapse sidebar"
                className="ml-auto flex-shrink-0 flex items-center justify-center h-7 w-7 rounded-[var(--bcone-radius-sm)] text-white/50 hover:bg-white/10 hover:text-white transition-colors"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            )}
          </>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-4">
        {sections.map((section, si) => (
          <div key={si}>
            {section.title && !collapsed && (
              <p className="px-2 mb-1 text-[10px] font-black uppercase tracking-widest text-white/40">
                {section.title}
              </p>
            )}
            <ul className="space-y-0.5">
              {section.items.map((item, ii) => {
                const cls = cn(
                  "w-full flex items-center gap-3 rounded-[var(--bcone-radius-sm)] px-2 py-2 text-sm transition-colors",
                  item.active
                    ? "bg-[var(--bcone-teal)] text-white"
                    : "text-white/70 hover:bg-white/10 hover:text-white",
                  collapsed && "justify-center"
                );
                const inner = (
                  <>
                    {item.icon && <span className="flex-shrink-0 h-5 w-5">{item.icon}</span>}
                    {!collapsed && (
                      <>
                        <span className="flex-1 text-left truncate">{item.label}</span>
                        {item.badge !== undefined && (
                          <span className="ml-auto text-xs bg-white/20 rounded-full px-1.5 py-0.5">
                            {item.badge}
                          </span>
                        )}
                      </>
                    )}
                  </>
                );
                return (
                  <li key={ii}>
                    {item.href ? (
                      <a
                        href={item.href}
                        title={collapsed ? item.label : undefined}
                        className={cls}
                        onClick={item.onClick}
                      >
                        {inner}
                      </a>
                    ) : (
                      <button
                        onClick={item.onClick}
                        title={collapsed ? item.label : undefined}
                        className={cls}
                      >
                        {inner}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Footer */}
      {footer && (
        <div className="border-t border-white/10 p-3">
          {footer}
        </div>
      )}

    </aside>
  );
};
