import * as React from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, LogOut, Settings, User } from "lucide-react";
import { cn } from "../../lib/utils";

export interface HeaderUser {
  name: string;
  email: string;
  avatarUrl?: string;
  role?: string;
}

export interface BristleconeHeaderProps {
  appName?: string;
  pageTitle?: string;
  user?: HeaderUser;
  onLogout?: () => void;
  onSettings?: () => void;
  actions?: React.ReactNode;
  logo?: React.ReactNode;
  className?: string;
  /** "light" = white bar (default), "dark" = bcone-black bar, "teal" = bcone-teal bar */
  variant?: "light" | "dark" | "teal";
}

export const BristleconeHeader: React.FC<BristleconeHeaderProps> = ({
  appName,
  pageTitle,
  user,
  onLogout,
  onSettings,
  actions,
  logo,
  className,
  variant = "light",
}) => {
  const colored = variant === "dark" || variant === "teal";

  return (
    <header
      className={cn(
        "flex items-center justify-between h-16 px-6 border-b shadow-[var(--bcone-shadow-sm)]",
        variant === "dark"  && "bg-[var(--bcone-black)] border-white/10",
        variant === "teal"  && "bg-[var(--bcone-teal)] border-white/20",
        variant === "light" && "bg-white border-[var(--bcone-gray)]/20",
        className
      )}
    >
      {/* Left: Logo + App name + optional page title */}
      <div className="flex items-center gap-3">
        {logo && <div className="flex-shrink-0">{logo}</div>}
        {appName && (
          <span className={cn("text-sm font-black", colored ? "text-white" : "text-[var(--bcone-charcoal)]")}>
            {appName}
          </span>
        )}
        {pageTitle && (
          <>
            <span className={cn("select-none", colored ? "text-white/40" : "text-[var(--bcone-gray)]/50")}>/</span>
            <span className={cn("text-sm font-bold", colored ? "text-white/80" : "text-[var(--bcone-teal)]")}>
              {pageTitle}
            </span>
          </>
        )}
      </div>

      {/* Right: actions + user menu */}
      <div className="flex items-center gap-3">
        {actions}

        {user && (
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button className={cn(
                "flex items-center gap-2 rounded-[var(--bcone-radius-sm)] px-2 py-1.5 transition-colors focus:outline-none focus:ring-2 focus:ring-white/40",
                colored ? "hover:bg-white/15" : "hover:bg-[var(--bcone-teal)]/8"
              )}>
                {user.avatarUrl ? (
                  <img
                    src={user.avatarUrl}
                    alt={user.name}
                    className="h-7 w-7 rounded-full object-cover"
                  />
                ) : (
                  <span className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-full text-xs font-black",
                    colored ? "bg-white/20 text-white" : "bg-[var(--bcone-teal)] text-white"
                  )}>
                    {user.name.slice(0, 2).toUpperCase()}
                  </span>
                )}
                <div className="text-left hidden sm:block">
                  <p className={cn("text-sm font-bold leading-none", colored ? "text-white" : "text-[var(--bcone-charcoal)]")}>{user.name}</p>
                  {user.role && (
                    <p className={cn("text-[10px] leading-none mt-0.5", colored ? "text-white/60" : "text-[var(--bcone-gray)]")}>{user.role}</p>
                  )}
                </div>
                <ChevronDown className={cn("h-4 w-4", colored ? "text-white/60" : "text-[var(--bcone-gray)]")} />
              </button>
            </DropdownMenu.Trigger>

            <DropdownMenu.Portal>
              <DropdownMenu.Content
                className="z-50 min-w-[200px] rounded-[var(--bcone-radius-md)] border border-[var(--bcone-gray)]/20 bg-white shadow-[var(--bcone-shadow-lg)] p-1"
                sideOffset={4}
                align="end"
              >
                <div className="px-3 py-2 border-b border-[var(--bcone-gray)]/10 mb-1">
                  <p className="text-sm font-bold text-[var(--bcone-charcoal)]">{user.name}</p>
                  <p className="text-xs text-[var(--bcone-gray)]">{user.email}</p>
                </div>

                {onSettings && (
                  <DropdownMenu.Item
                    onSelect={onSettings}
                    className="flex items-center gap-2 rounded-sm px-3 py-2 text-sm text-[var(--bcone-charcoal)] cursor-pointer hover:bg-[var(--bcone-teal)]/8 outline-none"
                  >
                    <Settings className="h-4 w-4 text-[var(--bcone-gray)]" />
                    Settings
                  </DropdownMenu.Item>
                )}

                {onLogout && (
                  <DropdownMenu.Item
                    onSelect={onLogout}
                    className="flex items-center gap-2 rounded-sm px-3 py-2 text-sm text-[var(--bcone-red)] cursor-pointer hover:bg-[var(--bcone-red)]/8 outline-none"
                  >
                    <LogOut className="h-4 w-4" />
                    Sign out
                  </DropdownMenu.Item>
                )}
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        )}

        {!user && (
          <div className="flex items-center gap-2 text-sm text-[var(--bcone-gray)]">
            <User className="h-4 w-4" />
            <span>Guest</span>
          </div>
        )}
      </div>
    </header>
  );
};
