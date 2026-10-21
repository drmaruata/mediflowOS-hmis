/**
 * Kiosk — route surface for /kiosk/tokens/:displayId (UI_UX_design §7
 * "Counter token display (kiosk)", §18.2 R1 inventory; UI-003).
 *
 * Scaffold placeholder, standalone and outside the interactive-auth shell: a
 * wall display renders no sidebar and no login prompt. Task 35 lands the
 * token display and its scoped read-only kiosk token; App.tsx lazy-loads
 * this file as the route element.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";

export default function KioskRoutes() {
  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-4">
      <Card className="w-full max-w-xl">
        <CardHeader>
          <h1 className="text-xl font-bold tracking-tight text-card-foreground">
            Counter Token Display
          </h1>
          <CardDescription>Not available yet (R1)</CardDescription>
        </CardHeader>
        <CardContent>
          <p role="status" className="text-sm text-muted-foreground">
            The token display is not built yet — this placeholder holds the
            /kiosk/tokens/:displayId route until the screen arrives with its
            release task.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
