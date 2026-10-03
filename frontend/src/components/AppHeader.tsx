/**
 * AppHeader — shadcn/ui based; supports drawer open / collapsed toggle.
 *
 * Props shaped by supermemory fixture (◪): `onOpenNav`, `onToggleCollapsed`.
 */
import { Activity, Menu, ChevronLeft } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export interface AppHeaderProps {
  isLive?: boolean;
  isCompact?: boolean;
  collapsed?: boolean;
  onOpenNav?: () => void;
  onToggleCollapsed?: () => void;
}

export function AppHeader({
  isLive = false,
  isCompact = false,
  collapsed = false,
  onOpenNav,
  onToggleCollapsed,
}: AppHeaderProps) {
  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur-md md:px-6">
      <div className="app-header__inner">
        <button
          aria-label="Open navigation"
          onClick={onOpenNav}
          className={isCompact ? "inline-flex" : "hidden"}
          disabled={!onOpenNav}
        >
          <Menu className="size-5 text-foreground" />
        </button>
        <button
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={onToggleCollapsed}
          className={!isCompact ? "inline-flex" : "hidden"}
          disabled={!onToggleCollapsed}
        >
          <ChevronLeft
            className={`size-5 text-foreground transition-transform ${collapsed ? "rotate-180" : ""}`}
          />
        </button>
        <div className="flex items-center gap-2.5">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary shadow-sm">
            <Activity className="size-5 text-primary-foreground" aria-hidden="true" />
          </div>
          <h1 className="text-lg font-semibold tracking-tight hidden md:block">Mediflow OS</h1>
        </div>
      </div>
      <div className="ml-auto flex items-center gap-3">
        <Badge
          variant={isLive ? "default" : "outline"}
          className={
            isLive
              ? "bg-green-600 hover:bg-green-700 text-white"
              : "text-muted-foreground"
          }
        >
          {isLive ? "Live Data" : "Demo data"}
        </Badge>
      </div>
    </header>
  );
}
