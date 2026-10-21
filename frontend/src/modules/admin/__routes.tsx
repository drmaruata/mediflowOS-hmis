/**
 * Admin — route surface for /admin/users (UI_UX_design §7 "Users
 * administration", §18.2 R1 inventory; TEN-004).
 *
 * Scaffold placeholder: it holds the route contract until Task 34 lands the
 * users, roles, departments, wards/beds and audit screens. App.tsx
 * lazy-loads this file as the /admin/users element.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";

export default function AdminRoutes() {
  return (
    <Card className="mx-auto max-w-xl">
      <CardHeader>
        <h1 className="text-xl font-bold tracking-tight text-card-foreground">
          Users & Roles
        </h1>
        <CardDescription>Not available yet (R1)</CardDescription>
      </CardHeader>
      <CardContent>
        <p role="status" className="text-sm text-muted-foreground">
          User and role administration is not built yet — this placeholder
          holds the /admin/users route until the screen arrives with its
          release task.
        </p>
      </CardContent>
    </Card>
  );
}
