/**
 * PatientDetail — the patient profile screen at /patients/:id (REG-001,
 * REG-006/007; UI_UX §7 "Patient profile / UHID").
 *
 * The route key is the record's UUID, not the UHID: the API retrieves by
 * primary key and no UHID-based lookup is exposed server-side, so the doc's
 * /patients/:uhid shape is served with the identifier the backend can
 * actually resolve (a foreign or unknown id answers 404, tenant-scoped).
 * The UHID is announced first, before the name (UI_UX accessibility note),
 * and the verification state is always visible text, never colour alone.
 */

import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { useSession } from "@/lib/session";
import { extractServerErrors } from "@/lib/serverErrors";
import { birthYearFromDemographics, fetchPatient, sameTenant, verificationLabel } from "./patient.api";

export default function PatientDetail() {
  const { id } = useParams<{ id: string }>();
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;

  const patient = useQuery({
    queryKey: ["patients", tenantId, id],
    queryFn: () => fetchPatient(id ?? ""),
    enabled: tenantId !== null && id !== undefined,
  });

  if (patient.isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading patient record…
      </p>
    );
  }

  if (patient.isError) {
    return (
      <p
        role="alert"
        className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
      >
        {extractServerErrors(patient.error).general ??
          "The patient record could not be loaded."}
      </p>
    );
  }

  const data = patient.data;
  if (!sameTenant(data, tenantId)) {
    // The server's RLS scope means this only fires on a broken response —
    // a foreign row must not render, exactly as on the list surfaces.
    return (
      <p
        role="alert"
        className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
      >
        This record does not belong to this hospital.
      </p>
    );
  }

  const year = birthYearFromDemographics(data.demographics);
  return (
    <div>
      <h1 className="font-mono text-xl font-bold tracking-tight text-card-foreground">
        {data.uhid}
      </h1>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Badge
          variant={data.verification_status === "verified" ? "secondary" : "outline"}
        >
          {verificationLabel(data.verification_status)}
        </Badge>
        {data.verified_at !== null && (
          <span className="text-xs text-muted-foreground">
            Verified at {new Date(data.verified_at).toLocaleString("en-IN")}
          </span>
        )}
      </div>

      <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <div className="flex gap-2">
          <dt className="text-muted-foreground">Name</dt>
          <dd className="font-medium">{String(data.demographics.name ?? "—")}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">Gender</dt>
          <dd className="font-medium">{String(data.demographics.gender ?? "—")}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">Birth year</dt>
          <dd className="font-medium">{year ?? "—"}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">Mobile</dt>
          <dd className="font-medium">{data.contact?.mobile ?? "—"}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">ABHA number</dt>
          <dd className="font-medium">{data.abha_number ?? "—"}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">ABHA address</dt>
          <dd className="font-medium">{data.abha_address ?? "—"}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">Intake channel</dt>
          <dd className="font-medium">{data.intake_channel || "unrecorded"}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">Registered</dt>
          <dd className="font-medium">
            {new Date(data.created_at).toLocaleDateString("en-IN")}
          </dd>
        </div>
      </dl>
    </div>
  );
}
