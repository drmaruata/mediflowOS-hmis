/**
 * BreakGlassDialog — recorded emergency access to one record (TEN-007,
 * P-ADM-4; UI_UX §7 "Break-glass flow").
 *
 * The grant is a server decision end to end: the dialog renders only for a
 * session whose `allows_break_glass` claim is true (the server still refuses
 * with its own 403 detail if the claim is stale), the reason is mandatory
 * and travels in the X-Break-Glass-Reason header the view reads — never the
 * body — and submit stays disabled until it is non-empty. The response is
 * rendered exactly as the API returns it: {access_id, granted_at}. The
 * endpoint does not expose expires_at/revoked_at (the model has them, the
 * serializer does not), so no expiry is shown and none is invented.
 */

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useSession } from "@/lib/session";
import { formAlertText, requestBreakGlass } from "./admin.api";
import type { BreakGlassGrant } from "./admin.api";

const reasonSchema = z.object({
  // The server strips before checking emptiness, so the client mirrors the
  // same rule — a whitespace-only reason must not look granted.
  reason: z.string().trim().min(1, "A reason is required for the audit trail."),
});

type ReasonValues = z.infer<typeof reasonSchema>;

const TEXTAREA_CLASS =
  "flex min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-invalid:border-destructive";

interface BreakGlassDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** AuditEvent-style entity name, e.g. "registry.patient". */
  resourceType: string;
  resourceId: string;
  /** Human label for the record being opened, e.g. the UHID. */
  resourceLabel: string;
}

export default function BreakGlassDialog({
  open,
  onOpenChange,
  resourceType,
  resourceId,
  resourceLabel,
}: BreakGlassDialogProps) {
  const session = useSession();
  const [grant, setGrant] = useState<BreakGlassGrant | null>(null);
  const form = useForm<ReasonValues>({
    resolver: zodResolver(reasonSchema),
    defaultValues: { reason: "" },
  });
  const request = useMutation({
    mutationFn: requestBreakGlass,
    onSuccess: (granted) => setGrant(granted),
  });

  // The claim is the render gate (ruling: cosmetic only — the server's 403
  // is what actually stops a claim-less session that reaches the endpoint).
  if (session.data?.allows_break_glass !== true) return null;

  const reason = form.watch("reason") ?? "";
  const close = (next: boolean) => {
    if (!next) {
      setGrant(null);
      request.reset();
      form.reset();
    }
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Emergency access (break-glass)</DialogTitle>
          <DialogDescription>
            Grants recorded access to {resourceLabel} outside your normal scope.
            The reason below is written to the audit trail and alerts
            privileged users; it cannot be edited afterwards.
          </DialogDescription>
        </DialogHeader>

        {grant !== null ? (
          <div role="status" className="grid gap-2 text-sm">
            <p className="font-medium">Emergency access granted.</p>
            <p>
              Access ID: <span className="font-mono">{grant.access_id}</span>
            </p>
            <p>
              Granted at: <span className="font-mono">{grant.granted_at}</span>
            </p>
            <p className="text-xs text-muted-foreground">
              The grant endpoint returns no expiry; the access is recorded for
              review and can be revoked administratively.
            </p>
          </div>
        ) : (
          <form
            noValidate
            onSubmit={form.handleSubmit((values) =>
              request.mutate({ resourceType, resourceId, reason: values.reason }),
            )}
          >
            <div className="grid gap-1.5">
              <Label htmlFor="break-glass-reason">Reason</Label>
              <textarea
                id="break-glass-reason"
                className={TEXTAREA_CLASS}
                aria-invalid={form.formState.errors.reason ? true : undefined}
                aria-describedby={
                  form.formState.errors.reason ? "break-glass-reason-error" : undefined
                }
                {...form.register("reason")}
              />
              {form.formState.errors.reason && (
                <p id="break-glass-reason-error" className="text-sm text-destructive">
                  {form.formState.errors.reason.message}
                </p>
              )}
            </div>
            {request.error !== null && (
              <p
                role="alert"
                className="mt-3 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {formAlertText(request.error) ?? "The grant could not be recorded."}
              </p>
            )}
            <DialogFooter className="mt-4">
              <Button type="button" variant="outline" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                variant="destructive"
                disabled={reason.trim() === "" || request.isPending}
              >
                {request.isPending ? "Recording…" : "Grant emergency access"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
