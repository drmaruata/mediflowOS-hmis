/**
 * VerificationQueue — the identity-verification work list at
 * /patients/verification-queue (P-REG-4/6, REG-006, ABD-009), fed by
 * GET /patients/verification_queue/: pending registrations and ambiguous
 * ABDM multi-candidate entries share one queue because the work is the
 * same — a human confirms identity.
 *
 * Verify is state-aware: only pending rows get the verify action (the
 * endpoint flips pending → verified and refuses anything else with 400),
 * ambiguous rows render their status and an honest note instead of a dead
 * button, and a 400 from a stale race (another clerk verified first)
 * surfaces the server's own detail rather than being swallowed while the
 * queue refetches to its true state. Polls every 5 s with a visible update
 * time and a manual refresh (UI_UX §7 awaiting-verification contract).
 */

import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ResourceSection } from "@/components/ResourceSection";
import { useSession } from "@/lib/session";
import { extractServerErrors } from "@/lib/serverErrors";
import { birthYearFromDemographics, fetchVerificationQueue, sameTenant, verifyPatient, verificationLabel } from "./patient.api";
import type { Patient } from "./patient.api";

const ageSex = (patient: Patient): string => {
  const sex = String(patient.demographics.gender ?? "—");
  const year = birthYearFromDemographics(patient.demographics);
  if (year === null) return sex;
  return `${new Date().getFullYear() - year}/${sex}`;
};

export default function VerificationQueue() {
  const queryClient = useQueryClient();
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;

  const queue = useQuery({
    queryKey: ["patients", tenantId, "verification-queue"],
    queryFn: fetchVerificationQueue,
    enabled: tenantId !== null,
    refetchInterval: 5_000,
  });

  const verify = useMutation({
    mutationFn: verifyPatient,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["patients", tenantId] });
    },
    onError: () => {
      // The row's state changed under us — refetch so the list tells the
      // truth; the alert below still says why the click failed.
      void queryClient.invalidateQueries({
        queryKey: ["patients", tenantId, "verification-queue"],
      });
    },
  });

  const rows = (queue.data ?? []).filter((patient) =>
    sameTenant(patient, tenantId),
  );

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-bold tracking-tight text-card-foreground">
          Verification queue
        </h2>
        <div className="flex items-center gap-3">
          {queue.dataUpdatedAt > 0 && (
            <p className="text-sm text-muted-foreground">
              Updated {new Date(queue.dataUpdatedAt).toLocaleTimeString("en-IN")}
            </p>
          )}
          <Button
            variant="outline"
            onClick={() => void queue.refetch()}
            disabled={queue.isFetching}
          >
            Refresh now
          </Button>
        </div>
      </div>

      {queue.isError && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {extractServerErrors(queue.error).general ??
            "Could not load the verification queue. Try refreshing."}
        </p>
      )}
      {verify.isError && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {extractServerErrors(verify.error).general ??
            "The verify action failed."}
        </p>
      )}

      <ResourceSection
        title="Verification queue"
        loading={queue.isPending}
        rows={rows}
        rowKey={(patient) => patient.id}
        emptyText="No patients awaiting verification. Verifying a patient removes them from this queue."
        columns={[
          {
            key: "registered",
            header: "Registered",
            render: (patient) => patient.created_at.slice(0, 10),
          },
          {
            key: "uhid",
            header: "UHID",
            render: (patient) => (
              <span className="font-mono text-xs">{patient.uhid}</span>
            ),
          },
          {
            key: "name",
            header: "Name",
            render: (patient) => String(patient.demographics.name ?? "—"),
          },
          { key: "agesex", header: "Age/Sex", render: ageSex },
          {
            key: "status",
            header: "Status",
            render: (patient) => (
              <Badge
                variant={
                  patient.verification_status === "pending"
                    ? "outline"
                    : "secondary"
                }
              >
                {verificationLabel(patient.verification_status)}
              </Badge>
            ),
          },
          {
            key: "record",
            header: "Record",
            render: (patient) => (
              <Link
                to={`/patients/${patient.id}`}
                className="text-primary underline-offset-4 hover:underline"
              >
                Open
              </Link>
            ),
          },
          {
            key: "action",
            header: "Action",
            render: (patient) =>
              patient.verification_status === "pending" ? (
                <Button
                  size="sm"
                  onClick={() => verify.mutate(patient.id)}
                  disabled={verify.isPending && verify.variables === patient.id}
                >
                  {verify.isPending && verify.variables === patient.id
                    ? "Verifying…"
                    : "Verify"}
                </Button>
              ) : (
                <span className="text-sm text-muted-foreground">
                  ABDM matched several records — resolve candidates first
                </span>
              ),
          },
        ]}
      />
    </div>
  );
}
