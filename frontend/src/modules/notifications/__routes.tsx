/**
 * Notifications — route surface for /notifications (UI_UX_design §7
 * "Notification centre", §18.2 R1 inventory).
 *
 * Scaffold placeholder: it holds the route contract until Task 37 lands the
 * bell and inbox. App.tsx lazy-loads this file as the /notifications element.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";

export default function NotificationsRoutes() {
  return (
    <Card className="mx-auto max-w-xl">
      <CardHeader>
        <h2 className="text-xl font-bold tracking-tight text-card-foreground">
          Notifications
        </h2>
        <CardDescription>Not available yet (R1)</CardDescription>
      </CardHeader>
      <CardContent>
        <p role="status" className="text-sm text-muted-foreground">
          The notification centre is not built yet — this placeholder holds
          the /notifications route until the screen arrives with its release
          task.
        </p>
      </CardContent>
    </Card>
  );
}
