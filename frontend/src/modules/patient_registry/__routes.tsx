/**
 * Patient registry — route surface for /patients (UI_UX_design §7 "Patient
 * registry — search/register", §18.2 R1 inventory; REG-001..007).
 *
 * Scaffold placeholder: it holds the route contract until Task 33 lands the
 * registration, search, duplicates and verification-queue screens. App.tsx
 * lazy-loads this file as the /patients element.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";

export default function PatientRegistryRoutes() {
  return (
    <Card className="mx-auto max-w-xl">
      <CardHeader>
        <h1 className="text-xl font-bold tracking-tight text-card-foreground">
          Patient Registration
        </h1>
        <CardDescription>Not available yet (R1)</CardDescription>
      </CardHeader>
      <CardContent>
        <p role="status" className="text-sm text-muted-foreground">
          Patient search and registration are not built yet — this placeholder
          holds the /patients route until the screen arrives with its release
          task.
        </p>
      </CardContent>
    </Card>
  );
}
