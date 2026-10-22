/**
 * MfaChallenge — second-factor challenge for privileged roles (TEN-006, UI-001).
 *
 * Rendered when the session reports requires_mfa && !mfa_verified: lists the
 * caller's authenticators, pending and confirmed. Confirming a pending device
 * or verifying against a confirmed one both return a fresh pair carrying
 * mfa_verified, so the store is swapped and the session refetched before the
 * MFA gate reopens the shell.
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
import { useAuthStore } from "@/stores/authStore";
import {
  confirmMfaDevice,
  listMfaDevices,
  verifyMfaToken,
} from "./auth.api";
import type { ConfirmMfaDeviceResponse, MfaDevice, TokenPair } from "./auth.api";

export default function MfaChallenge() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const session = useSession();
  const setTokens = useAuthStore((s) => s.setTokens);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [unverifiable, setUnverifiable] = useState(false);

  const devicesQuery = useQuery({
    queryKey: ["auth", "mfa-devices"],
    queryFn: listMfaDevices,
    retry: false,
  });

  const devices = devicesQuery.data ?? [];
  const selected =
    devices.find((device) => device.persistent_id === deviceId) ?? devices[0];

  // Regression guard (UI-001): if the minted pair somehow did not carry the
  // claim — or an older backend minted none — a still-unverified session
  // stays here with an honest notice instead of navigating into the gate's
  // redirect loop.
  const challengeMutation = useMutation({
    mutationFn: async ({
      device,
      token,
    }: {
      device: MfaDevice;
      token: string;
    }): Promise<TokenPair | ConfirmMfaDeviceResponse> =>
      // A pending device is confirmed (first enrolment); a confirmed one is
      // verified (later sessions). Either way the backend completes the
      // session in the same request.
      device.confirmed
        ? verifyMfaToken(token)
        : confirmMfaDevice(device.persistent_id, token),
    onSuccess: async (result) => {
      const pair =
        "access" in result && "refresh" in result
          ? { access: result.access, refresh: result.refresh }
          : null;
      if (pair) {
        setTokens(pair.access, pair.refresh);
      }
      await queryClient.refetchQueries({ queryKey: ["auth", "me"] });
      const me = queryClient.getQueryData<Session>(["auth", "me"]);
      if (me?.requires_mfa && !me.mfa_verified) {
        setUnverifiable(true);
        return;
      }
      await queryClient.invalidateQueries({ queryKey: ["auth", "mfa-devices"] });
      void navigate("/dashboard", { replace: true });
    },
  });

  // Already verified (or not required): nothing to challenge.
  if (session.data && (!session.data.requires_mfa || session.data.mfa_verified)) {
    return <Navigate to="/" replace />;
  }

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (selected) {
      challengeMutation.mutate({ device: selected, token: code });
    }
  };

  return (
    <div className="flex min-h-svh items-center justify-center bg-card p-4">
      <Card className="w-full max-w-[420px] border bg-card shadow-sm">
        <CardHeader className="pb-4 text-center">
          <h1 className="flex items-center justify-center gap-2 text-xl font-bold tracking-tight text-card-foreground">
            <ShieldCheck className="size-5 text-primary" aria-hidden="true" />
            Two-factor authentication
          </h1>
          <CardDescription>
            Your role requires a second factor. Enter a code from your
            authenticator to continue.
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
          ) : devices.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No pending authenticator is registered for your account. Ask
              your administrator to enrol one.
            </p>
          ) : (
            <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
              <fieldset className="flex flex-col gap-2">
                <legend className="sr-only">Your authenticators</legend>
                {devices.map((device) => (
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
                  aria-invalid={challengeMutation.isError || undefined}
                  autoFocus
                />
              </div>

              {challengeMutation.isError && (
                <p role="alert" className="text-sm text-destructive">
                  {challengeMutation.error instanceof ApiError &&
                  challengeMutation.error.status === 429
                    ? "Too many attempts. Wait a minute and try again."
                    : "That code didn't match. Check your authenticator and try again."}
                </p>
              )}

              <Button
                type="submit"
                className="h-11 w-full text-sm font-semibold"
                disabled={
                  !selected || code.trim() === "" || challengeMutation.isPending
                }
              >
                {challengeMutation.isPending ? (
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
