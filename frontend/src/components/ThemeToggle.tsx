/**
 * ThemeToggle — light / dark / system theme control.
 *
 * Spec: design.md §16, UI-002, UI_UX_design §12 (icon-only controls always
 * have an accessible name; 44x44px targets on tablet).
 *
 * Written against the shadcn `dark` class-driven pattern. The pre-paint
 * bootstrap in `index.html` owns the first paint; this component owns every
 * subsequent change and persists the choice.
 */

import { Monitor, Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useThemeStore,
  type ThemePreference,
} from "@/stores/themeStore";

const OPTIONS: ReadonlyArray<{
  value: ThemePreference;
  label: string;
  icon: typeof Sun;
}> = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

export interface ThemeToggleProps {
  /**
   * Surface overrides. The toggle lives on the dark top bar today
   * (`#153047`), where the default `ghost` variant would inherit light-theme
   * text colours; `onDarkSurface` keeps the icon legible.
   */
  onDarkSurface?: boolean;
}

export function ThemeToggle({ onDarkSurface = false }: ThemeToggleProps = {}) {
  const preference = useThemeStore((s) => s.preference);
  const resolved = useThemeStore((s) => s.resolved);
  const setPreference = useThemeStore((s) => s.setPreference);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Theme: ${preference}`}
          title={`Theme: ${preference}`}
          className={
            onDarkSurface
              ? "size-10 text-white hover:bg-white/10 hover:text-white"
              : "size-10"
          }
        >
          {resolved === "dark" ? (
            <Moon className="size-4" aria-hidden="true" />
          ) : (
            <Sun className="size-4" aria-hidden="true" />
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuLabel>Appearance</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={preference}
          onValueChange={(value) => setPreference(value as ThemePreference)}
        >
          {OPTIONS.map(({ value, label, icon: Icon }) => (
            <DropdownMenuRadioItem key={value} value={value} className="gap-2">
              <Icon className="size-4" aria-hidden="true" />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}