/**
 * MfaChallenge — second-factor confirmation for privileged roles (TEN-006, UI-001).
 *
 * Rendered when the session reports requires_mfa && !mfa_verified: lists the
 * caller's pending authenticators, confirms one with a TOTP, then rotates the
 * access token and refetches the session so the MFA gate reopens to the shell.
 */

import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";
import { ApiError } from "@/lib/apiClient";
import { useSession } from "@/lib/session";
import type { Session } from "@/lib/session";
import { refreshSession } from "@/lib/tokenRefresh";
import { confirmMfaDevice, listMfaDevices } from "./auth.api";

export default function MfaChallenge() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const session = useSession();
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [unverifiable, setUnverifiable] = useState(false);

  const devicesQuery = useQuery({
    queryKey: ["auth", "mfa-devices"],
    queryFn: listMfaDevices,
    retry: false,
  });

  const pending = (devicesQuery.data ?? []).filter(
    (device) => !device.confirmed,
  );
  const selected =
    pending.find((device) => device.persistent_id === deviceId) ?? pending[0];

  // Partial (UI-001): the backend cannot yet mint mfa_verified, so a still-unverified session after confirm stays here with an honest notice instead of navigating into the gate's redirect loop.
  const confirmMutation = useMutation({
    mutationFn: (input: { persistentId: string; token: string }) =>
      confirmMfaDevice(input.persistentId, input.token),
    onSuccess: async () => {
      // Rotate so the new access token carries the second factor, then make
      // the session current before navigating — the gate reads /auth/me/.
      if (!(await refreshSession())) {
        return; // session died mid-challenge; AuthGuard redirects to /login
      }
      await queryClient.refetchQueries({ queryKey: ["auth", "me"] });
      const me = queryClient.getQueryData<Session>(["auth", "me"]);
      if (me?.requires_mfa && !me.mfa_verified) {
        setUnverifiable(true);
        return;
      }
      await queryClient.invalidateQueries({ queryKey: ["auth", "mfa-devices"] });
      void navigate("/", { replace: true });
    },
  });

  // Already verified (or not required): nothing to challenge.
  if (session.data && (!session.data.requires_mfa || session.data.mfa_verified)) {
    return <Navigate to="/" replace />;
  }

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (selected) {
      confirmMutation.mutate({ persistentId: selected.persistent_id, token: code });
    }
  };

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-4">
      <Card className="w-full max-w-[420px] border bg-card shadow-sm">
        <CardHeader className="pb-4 text-center">
          <h1 className="flex items-center justify-center gap-2 text-xl font-bold tracking-tight text-card-foreground">
            <ShieldCheck className="size-5 text-primary" aria-hidden="true" />
            Two-factor authentication
          </h1>
          <CardDescription>
            Your role requires a second factor. Confirm your authenticator to
            continue.
          </CardDescription>
        </CardHeader>

        <CardContent>
          {unverifiable ? (
            <p role="status" className="text-sm text-muted-foreground">
              Authenticator confirmed. This deployment cannot yet issue a
              verified session — sign out and try again later, or contact
              your administrator.
            </p>
          ) : devicesQuery.isPending ? (
            <p className="text-sm text-muted-foreground">
              Loading your devices…
            </p>
          ) : devicesQuery.isError ? (
            <p role="alert" className="text-sm text-destructive">
              Couldn't load your authenticators. Refresh the page and try
              again.
            </p>
          ) : pending.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No pending authenticator is registered for your account. Ask
              your administrator to enrol one.
            </p>
          ) : (
            <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
              <fieldset className="flex flex-col gap-2">
                <legend className="sr-only">Pending authenticators</legend>
                {pending.map((device) => (
                  <label
                    key={device.persistent_id}
                    className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm text-foreground"
                  >
                    <input
                      type="radio"
                      name="mfa-device"
                      value={device.persistent_id}
                      checked={selected?.persistent_id === device.persistent_id}
                      onChange={() => setDeviceId(device.persistent_id)}
                      className="size-4 accent-primary"
                    />
                    {device.name}
                  </label>
                ))}
              </fieldset>

              <div className="grid gap-1.5">
                <Label htmlFor="mfa-code">Authenticator code</Label>
                <Input
                  id="mfa-code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="6-digit code"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  aria-invalid={confirmMutation.isError || undefined}
                  autoFocus
                />
              </div>

              {confirmMutation.isError && (
                <p role="alert" className="text-sm text-destructive">
                  {confirmMutation.error instanceof ApiError &&
                  confirmMutation.error.status === 429
                    ? "Too many attempts. Wait a minute and try again."
                    : "That code didn't match. Check your authenticator and try again."}
                </p>
              )}

              <Button
                type="submit"
                className="h-11 w-full text-sm font-semibold"
                disabled={!selected || code.trim() === "" || confirmMutation.isPending}
              >
                {confirmMutation.isPending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                    Verifying…
                  </>
                ) : (
                  "Verify and continue"
                )}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
