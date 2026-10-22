/**
 * PatientList — the counter's patient lookup at /patients (REG-002;
 * UI_UX §7 "Patient registry — search/register").
 *
 * Search goes to the `search` action (GET /patients/search/?q=), never the
 * plain list: the list endpoint is the bulk 50-row audit-logged roster (one
 * PHI read per row), while the action is the ≤20-row materialized page the
 * counter lookup is specified against. No plain roster view is offered —
 * that surface belongs to the admin table screens.
 *
 * REG-008 honesty: mobile and ABHA are encrypted with exact-match indexes,
 * so only a complete number matches. The hint and the empty state say so
 * instead of leaving a silent no-match a clerk would read as "no such
 * patient".
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ResourceSection } from "@/components/ResourceSection";
import { useSession } from "@/lib/session";
import { extractServerErrors } from "@/lib/serverErrors";
import { birthYearFromDemographics, sameTenant, searchPatients, verificationLabel } from "./patient.api";
import type { Patient } from "./patient.api";

/** The server's 20-row search cap — at that size the page may be truncated. */
const SEARCH_PAGE_CAP = 20;

const ageSex = (patient: Patient): string => {
  const sex = String(patient.demographics.gender ?? "—");
  const year = birthYearFromDemographics(patient.demographics);
  if (year === null) return sex;
  return `${new Date().getFullYear() - year}/${sex}`;
};

export default function PatientList() {
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;
  const [term, setTerm] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);

  const search = useQuery({
    queryKey: ["patients", tenantId, { search: submitted }],
    queryFn: () => searchPatients(submitted ?? ""),
    enabled: tenantId !== null && submitted !== null,
  });

  const rows = (search.data ?? []).filter((patient) =>
    sameTenant(patient, tenantId),
  );

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold tracking-tight text-card-foreground">
          Patients
        </h1>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link to="/patients/register">New patient</Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/patients/verification-queue">Verification queue</Link>
          </Button>
        </div>
      </div>

      <form
        className="mt-4 flex flex-wrap items-end gap-2"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(term);
        }}
      >
        <div className="grid flex-1 gap-1.5 sm:max-w-md">
          <Label htmlFor="patient-search" className="sr-only">
            Search patients
          </Label>
          <Input
            id="patient-search"
            type="search"
            autoFocus
            placeholder="UHID, name, complete mobile or ABHA number"
            value={term}
            onChange={(event) => setTerm(event.target.value)}
          />
        </div>
        <Button type="submit">Search</Button>
      </form>

      <p className="mt-2 text-xs text-muted-foreground">
        Name and UHID match partial text. Mobile and ABHA numbers are
        encrypted at rest (REG-008) — only the complete number matches; a
        fragment deliberately matches nothing.
      </p>

      {search.isError && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {extractServerErrors(search.error).general ??
            "The search could not run. Try again."}
        </p>
      )}

      {submitted === null ? null : (
        <ResourceSection
          title="Search results"
          loading={search.isPending}
          rows={rows}
          rowKey={(patient) => patient.id}
          emptyText="No patients match. Name and UHID match partial text; mobile and ABHA match the complete number only."
          columns={[
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
              key: "mobile",
              header: "Mobile",
              render: (patient) => patient.contact?.mobile ?? "—",
            },
            {
              key: "abha",
              header: "ABHA",
              render: (patient) => patient.abha_number ?? "—",
            },
            {
              key: "status",
              header: "Status",
              render: (patient) => (
                <Badge
                  variant={
                    patient.verification_status === "verified"
                      ? "secondary"
                      : "outline"
                  }
                >
                  {verificationLabel(patient.verification_status)}
                </Badge>
              ),
            },
            {
              key: "open",
              header: "Open",
              render: (patient) => (
                <Link
                  to={`/patients/${patient.id}`}
                  className="text-primary underline-offset-4 hover:underline"
                >
                  Open
                </Link>
              ),
            },
          ]}
        >
          {rows.length >= SEARCH_PAGE_CAP && (
            <p className="mt-1 text-sm text-muted-foreground">
              The search returns at most {SEARCH_PAGE_CAP} matches — narrow the
              term to see more.
            </p>
          )}
        </ResourceSection>
      )}
    </div>
  );
}
