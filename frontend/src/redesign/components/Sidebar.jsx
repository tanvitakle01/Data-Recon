import { PanelLeftClose, PanelLeft, Sun, Moon } from "lucide-react";
import { cn } from "../lib/cn";
import { Tooltip } from "./Tooltip";
import { Stepper } from "./Stepper";

function NavItem({ item, active, collapsed, onClick }) {
  const btn = (
    <button
      onClick={() => onClick?.(item.key)}
      className={cn(
        "group relative flex w-full items-center gap-3 rounded-lg py-2 text-[13px] font-medium transition-colors",
        collapsed ? "justify-center px-0 h-9" : "px-3",
        active ? "bg-accent-tint text-accent-text" : "text-text-secondary hover:bg-surface-2 hover:text-text"
      )}
    >
      {active && <span className="absolute left-0 top-1/2 h-5 -translate-y-1/2 w-[3px] rounded-r-full bg-accent" />}
      <span className={cn("shrink-0", active ? "text-accent-text" : "text-muted group-hover:text-text")}>{item.icon}</span>
      {!collapsed && <span className="truncate">{item.label}</span>}
      {!collapsed && item.trailing}
    </button>
  );
  return collapsed ? (
    <Tooltip content={item.label} side="right">
      {btn}
    </Tooltip>
  ) : (
    btn
  );
}

export function Sidebar({
  collapsed = false,
  onToggleCollapse,
  brand = "Data Recon",
  nav = [],
  active,
  onNavClick,
  wizard, // { steps, onStepClick, context, quickLinks }
  dark = false,
  onToggleDark,
  user,
  className,
}) {
  return (
    <aside
      className={cn(
        "flex h-full flex-col border-r border-line bg-surface transition-[width] duration-200 ease-[cubic-bezier(0.2,0,0,1)]",
        collapsed ? "w-[68px]" : "w-[264px]",
        className
      )}
    >
      {/* brand */}
      <div className={cn("flex h-14 shrink-0 items-center gap-2.5 border-b border-line", collapsed ? "justify-center px-0" : "px-4")}>
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent text-on-accent shadow-e1">
          <span className="font-mono text-[13px] font-bold">DR</span>
        </div>
        {!collapsed && <span className="truncate text-[14px] font-semibold tracking-[-0.01em]">{brand}</span>}
      </div>

      {/* nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-3">
        <div className="flex flex-col gap-0.5">
          {nav.map((item) => (
            <div key={item.key}>
              <NavItem item={item} active={active === item.key} collapsed={collapsed} onClick={onNavClick} />
              {/* embedded wizard navigator under the active reconciliation item */}
              {!collapsed && wizard && active === item.key && item.key === "reconciliation" && (
                <div className="mt-1.5 mb-2 ml-3 border-l border-line pl-3">
                  <Stepper steps={wizard.steps} onStepClick={wizard.onStepClick} />

                  {wizard.context?.length > 0 && (
                    <div className="mt-3 rounded-lg bg-surface-2 p-2.5">
                      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">Context</p>
                      <dl className="flex flex-col gap-1">
                        {wizard.context.map((c) => (
                          <div key={c.label} className="flex items-baseline justify-between gap-2">
                            <dt className="text-[11px] text-muted">{c.label}</dt>
                            <dd className={cn("truncate text-[11px] text-text-secondary", c.mono && "font-mono")}>{c.value}</dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  )}

                  {wizard.quickLinks?.length > 0 && (
                    <div className="mt-2 flex flex-col gap-0.5">
                      <p className="mb-1 mt-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">Jump to</p>
                      {wizard.quickLinks.map((q) => (
                        <button
                          key={q.label}
                          disabled={q.disabled}
                          onClick={q.onClick}
                          className="flex items-center gap-2 rounded-md px-2 py-1 text-left text-[12px] text-text-secondary transition-colors hover:bg-surface-3 disabled:opacity-40 disabled:hover:bg-transparent"
                        >
                          <span className="text-muted">{q.icon}</span>
                          <span className="truncate">{q.label}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </nav>

      {/* footer */}
      <div className={cn("shrink-0 border-t border-line p-3", collapsed && "flex flex-col items-center gap-1")}>
        <div className={cn("flex items-center", collapsed ? "flex-col gap-1" : "justify-between")}>
          <Tooltip content={dark ? "Light mode" : "Dark mode"} side={collapsed ? "right" : "top"}>
            <button
              onClick={onToggleDark}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-text"
            >
              {dark ? <Sun className="h-[18px] w-[18px]" /> : <Moon className="h-[18px] w-[18px]" />}
            </button>
          </Tooltip>
          <Tooltip content={collapsed ? "Expand" : "Collapse"} side={collapsed ? "right" : "top"}>
            <button
              onClick={onToggleCollapse}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-text"
            >
              {collapsed ? <PanelLeft className="h-[18px] w-[18px]" /> : <PanelLeftClose className="h-[18px] w-[18px]" />}
            </button>
          </Tooltip>
        </div>
        {!collapsed && user && (
          <div className="mt-2 flex items-center gap-2.5 rounded-lg px-1 py-1">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-tint text-[11px] font-semibold text-accent-text">
              {user.initials}
            </div>
            <div className="min-w-0">
              <p className="truncate text-[12px] font-medium text-text">{user.name}</p>
              <p className="truncate text-[11px] text-muted">{user.role}</p>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

export default Sidebar;
