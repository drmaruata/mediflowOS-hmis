/**
 * Facility setup — route surface for /admin/setup (UI_UX_design §7 "Facility
 * setup wizard", §18.2 R1 inventory; SET-001).
 *
 * Scaffold placeholder: it holds the route contract until Task 32 lands the
 * resumable wizard. App.tsx lazy-loads this file as the /admin/setup element;
 * a nav item whose path is routed must land on a real screen, never a blank
 * content area (AGENTS.md §5).
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";

export default function SetupRoutes() {
  return (
    <Card className="mx-auto max-w-xl">
      <CardHeader>
        <h1 className="text-xl font-bold tracking-tight text-card-foreground">
          Facility Setup
        </h1>
        <CardDescription>Not available yet (R1)</CardDescription>
      </CardHeader>
      <CardContent>
        <p role="status" className="text-sm text-muted-foreground">
          The setup wizard is not built yet — this placeholder holds the
          /admin/setup route until the screen arrives with its release task.
        </p>
      </CardContent>
    </Card>
  );
}
