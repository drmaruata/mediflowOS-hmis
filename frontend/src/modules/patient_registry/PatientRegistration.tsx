/**
 * PatientRegistration — the counter's new-patient form (REG-001, REG-003,
 * REG-005, REG-007; UI_UX §7 "Patient registry — search/register"), laid
 * out as the OPD design's single "Patient information" card with an
 * orientation guide beside it.
 *
 * The age is derived from the entered date of birth (ageFromDob) and shown
 * read-only — the approximate-age input the card once had is gone, so the
 * mandatory DoB is the birth key REG-007 needs. ABHA capture stays optional
 * under the contact row. The duplicate check (REG-003) runs on blur of the
 * name/DoB/mobile/ABHA fields and is advisory: "register anyway" needs an
 * explicit checkbox, and the create itself is the server's to accept or
 * refuse. The UHID is minted by the server (REG-001) — no UHID field exists
 * here and only the create response's identifier is ever rendered.
 */

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSession } from "@/lib/session";
import { extractServerErrors } from "@/lib/serverErrors";
import { DuplicateWarning } from "./DuplicateWarning";
import {
  ageFromDob,
  buildRegistrationPayload,
  createPatient,
  duplicateCheck,
  fetchOpdDepartments,
  isValidIndianMobile,
} from "./patient.api";
import type { DuplicateCheckInput } from "./patient.api";

const GENDERS = ["male", "female", "other"] as const;

const GUIDE_STEPS = [
  { title: "Patient details", detail: "Verify identity and contact information." },
  { title: "Department", detail: "Route the patient to the correct specialty." },
  { title: "Queue token", detail: "Assigned to the department after registration." },
] as const;

const registrationSchema = z
  .object({
    name: z
      .string()
      .trim()
      .min(2, "Enter the patient's full name.")
      .max(200, "The name is too long (max 200 characters)."),
    gender: z.string().min(1, "Select a gender."),
    dob: z.string(),
    address: z.string().trim().min(1, "Enter the patient's address."),
    mobile: z.string(),
    abha_number: z.string(),
    intake_department_id: z.string().min(1, "Select the OP intake department."),
  })
  .superRefine((values, ctx) => {
    // The age is derived from the DoB, so a real, past date is the only
    // birth key left (REG-007's dob-or-age passes through dob alone).
    if (values.dob === "") {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["dob"],
        message: "Enter the patient's date of birth.",
      });
    } else {
      const born = new Date(`${values.dob}T00:00:00`);
      if (
        Number.isNaN(born.valueOf()) ||
        born.valueOf() > new Date().valueOf()
      ) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["dob"],
          message: "Enter a real date of birth that is not in the future.",
        });
      }
    }
    // The OPD design marks the contact number required; the server keeps
    // accepting registrations without one, this screen just asks first.
    if (values.mobile.trim() === "") {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["mobile"],
        message: "Enter the patient's contact number.",
      });
    } else if (!isValidIndianMobile(values.mobile)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["mobile"],
        message: "Enter a 10-digit Indian mobile number (optionally prefixed +91).",
      });
    }
  });

type RegistrationValues = z.infer<typeof registrationSchema>;

const selectClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-invalid:border-destructive";

const textareaClass =
  "flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm min-h-20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-invalid:border-destructive";

export default function PatientRegistration() {
  const queryClient = useQueryClient();
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;

  const departments = useQuery({
    queryKey: ["departments", tenantId, "opd"],
    queryFn: fetchOpdDepartments,
    enabled: tenantId !== null,
  });

  const form = useForm<RegistrationValues>({
    resolver: zodResolver(registrationSchema),
    defaultValues: {
      name: "",
      gender: "",
      dob: "",
      address: "",
      mobile: "",
      abha_number: "",
      intake_department_id: "",
    },
  });
  const { register, handleSubmit, getValues, setError, reset } = form;
  const errors = form.formState.errors;

  // The age input is derived state: watch the DoB and compute, never store.
  const dobValue = form.watch("dob");
  const age = ageFromDob(dobValue);

  const [acknowledged, setAcknowledged] = useState(false);
  const [ackRequired, setAckRequired] = useState(false);

  const successRef = useRef<HTMLDivElement | null>(null);

  const duplicates = useMutation({
    mutationFn: duplicateCheck,
    // A confirmation made for older candidates proves nothing about the
    // ones a new probe just returned.
    onSuccess: () => setAcknowledged(false),
  });
  const lastProbe = useRef("");
  const runDuplicateCheck = () => {
    const values = getValues();
    const candidate: DuplicateCheckInput = {};
    if (values.name.trim() !== "") candidate.name = values.name.trim();
    if (values.dob !== "") candidate.dob = values.dob;
    if (values.mobile.trim() !== "") candidate.mobile = values.mobile.trim();
    if (values.abha_number.trim() !== "") {
      candidate.abha_number = values.abha_number.trim();
    }
    // A birth key alone can never warn (the server matches name AND year,
    // mobile, or ABHA), so an empty identity is not worth a round-trip.
    if (
      candidate.name === undefined &&
      candidate.mobile === undefined &&
      candidate.abha_number === undefined
    ) {
      return;
    }
    const fingerprint = JSON.stringify(candidate);
    if (fingerprint === lastProbe.current) return;
    lastProbe.current = fingerprint;
    duplicates.mutate(candidate);
  };

  const create = useMutation({
    mutationFn: (values: RegistrationValues) =>
      createPatient(buildRegistrationPayload(values)),
    onSuccess: () => {
      setAcknowledged(false);
      setAckRequired(false);
      void queryClient.invalidateQueries({ queryKey: ["patients", tenantId] });
    },
    onError: (error) => {
      const { fieldErrors } = extractServerErrors(error);
      if (fieldErrors.intake_department_id !== undefined) {
        setError("intake_department_id", {
          message: fieldErrors.intake_department_id,
        });
      }
      if (fieldErrors.abha_number !== undefined) {
        setError("abha_number", { message: fieldErrors.abha_number });
      }
    },
  });

  useEffect(() => {
    if (create.isSuccess) successRef.current?.focus();
  }, [create.isSuccess]);

  const failure =
    create.isError && create.error !== null
      ? extractServerErrors(create.error)
      : null;
  // contact/demographics refusals have no single form field: surface them
  // as the alert instead of dropping the server's message.
  const failureText =
    failure === null
      ? null
      : (
          [
            failure.general,
            ...Object.entries(failure.fieldErrors)
              .filter(
                ([key]) =>
                  key !== "intake_department_id" && key !== "abha_number",
              )
              .map(([, message]) => message),
          ] as Array<string | null>
        )
          .filter((part): part is string => part !== null)
          .join(" ") || null;

  const submitRegistration = handleSubmit((values) => {
    const warning =
      duplicates.data !== undefined &&
      duplicates.data.warn &&
      duplicates.data.candidates.length > 0;
    if (warning && !acknowledged) {
      setAckRequired(true);
      return;
    }
    setAckRequired(false);
    create.mutate(values);
  });

  const clearForm = () => {
    reset();
    duplicates.reset();
    lastProbe.current = "";
    setAcknowledged(false);
    setAckRequired(false);
  };

  const nameField = register("name", { onBlur: runDuplicateCheck });
  const dobField = register("dob", { onBlur: runDuplicateCheck });
  const mobileField = register("mobile", { onBlur: runDuplicateCheck });
  const abhaField = register("abha_number", { onBlur: runDuplicateCheck });
  const genderField = register("gender");
  const departmentField = register("intake_department_id");

  if (create.isSuccess && create.data !== undefined) {
    const patient = create.data;
    return (
      <div>
        <h2 className="text-xl font-bold tracking-tight text-card-foreground">
          Patient registered
        </h2>
        <div
          ref={successRef}
          role="status"
          tabIndex={-1}
          className="mt-4 rounded-md border border-primary/40 bg-primary/5 p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <p className="text-sm text-muted-foreground">
            UHID — issued by the registry
          </p>
          <p className="font-mono text-2xl font-bold tracking-tight text-foreground">
            {patient.uhid}
          </p>
          {patient.token !== undefined ? (
            <p className="mt-2 text-sm text-foreground">
              OPD token{" "}
              <span className="font-semibold">
                {patient.token.series}-{patient.token.number}
              </span>{" "}
              — the patient is in the queue.
            </p>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">
              No OPD token was issued.
            </p>
          )}
          <p className="mt-2 text-xs text-muted-foreground">
            OP slip ready — click "Print OP slip" to open the print view.
          </p>
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button asChild>
            <Link to={`/patients/${patient.id}`}>Open patient record</Link>
          </Button>
          {patient.token !== undefined && patient.visit_id !== undefined && (
            <Button asChild variant="outline">
              <Link to={`/print/op-slip/${patient.visit_id}`}>Print OP slip</Link>
            </Button>
          )}
          <Button variant="outline" onClick={clearForm}>
            Register another patient
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-primary">
              ● OPD registration
            </p>
            <h2 className="mt-1 text-2xl font-bold tracking-tight text-foreground">
              Register a new patient
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Create a patient profile before assigning a consultation token.
            </p>
          </div>
          <Button asChild variant="outline">
            <Link to="/patients">Back to patients</Link>
          </Button>
        </div>

        <Card className="mt-6">
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div className="grid gap-1.5">
                <CardTitle className="text-xl font-bold">
                  Patient information
                </CardTitle>
                <CardDescription>
                  Fields marked with an asterisk are required.
                </CardDescription>
              </div>
              <span className="font-mono text-xs uppercase tracking-wide text-primary">
                New record
              </span>
            </div>
          </CardHeader>
          <CardContent>
            {failureText !== null && (
              <p
                role="alert"
                className="mb-5 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {failureText}
              </p>
            )}
            <form
              onSubmit={submitRegistration}
              noValidate
              className="flex flex-col gap-5"
            >
              <div className="grid gap-1.5">
                <Label htmlFor="patient-name">Patient name *</Label>
                <Input
                  id="patient-name"
                  type="text"
                  autoComplete="off"
                  placeholder="Enter patient's full name"
                  aria-invalid={errors.name ? true : undefined}
                  aria-describedby={
                    errors.name ? "patient-name-error" : undefined
                  }
                  {...nameField}
                />
                {errors.name && (
                  <p id="patient-name-error" className="text-sm text-destructive">
                    {errors.name.message}
                  </p>
                )}
              </div>

              <div className="grid gap-5 sm:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="patient-gender">Gender *</Label>
                  <select
                    id="patient-gender"
                    className={selectClass}
                    aria-invalid={errors.gender ? true : undefined}
                    aria-describedby={
                      errors.gender ? "patient-gender-error" : undefined
                    }
                    {...genderField}
                  >
                    <option value="">Select gender</option>
                    {GENDERS.map((gender) => (
                      <option key={gender} value={gender}>
                        {gender.charAt(0).toUpperCase() + gender.slice(1)}
                      </option>
                    ))}
                  </select>
                  {errors.gender && (
                    <p
                      id="patient-gender-error"
                      className="text-sm text-destructive"
                    >
                      {errors.gender.message}
                    </p>
                  )}
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="patient-dob">Date of birth *</Label>
                  <Input
                    id="patient-dob"
                    type="date"
                    aria-invalid={errors.dob ? true : undefined}
                    aria-describedby={
                      errors.dob ? "patient-dob-error" : undefined
                    }
                    {...dobField}
                  />
                  {errors.dob && (
                    <p id="patient-dob-error" className="text-sm text-destructive">
                      {errors.dob.message}
                    </p>
                  )}
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="patient-age">Age</Label>
                  <Input
                    id="patient-age"
                    type="text"
                    readOnly
                    value={age === null ? "" : String(age)}
                    placeholder="Calculated from date of birth"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="patient-contact">Contact number *</Label>
                  <Input
                    id="patient-contact"
                    type="tel"
                    autoComplete="off"
                    placeholder="+91 98765 43210"
                    aria-invalid={errors.mobile ? true : undefined}
                    aria-describedby={
                      errors.mobile ? "patient-mobile-error" : undefined
                    }
                    {...mobileField}
                  />
                  {errors.mobile && (
                    <p
                      id="patient-mobile-error"
                      className="text-sm text-destructive"
                    >
                      {errors.mobile.message}
                    </p>
                  )}
                </div>
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="patient-address">Address *</Label>
                <textarea
                  id="patient-address"
                  className={textareaClass}
                  placeholder="House number, street, city, state and postal code"
                  aria-invalid={errors.address ? true : undefined}
                  aria-describedby={
                    errors.address ? "patient-address-error" : undefined
                  }
                  {...register("address")}
                />
                {errors.address && (
                  <p
                    id="patient-address-error"
                    className="text-sm text-destructive"
                  >
                    {errors.address.message}
                  </p>
                )}
              </div>

              <div className="grid gap-1.5 sm:max-w-md">
                <Label htmlFor="patient-abha">ABHA number (if known)</Label>
                <Input
                  id="patient-abha"
                  type="text"
                  autoComplete="off"
                  aria-invalid={errors.abha_number ? true : undefined}
                  aria-describedby={
                    errors.abha_number ? "patient-abha-error" : undefined
                  }
                  {...abhaField}
                />
                {errors.abha_number && (
                  <p
                    id="patient-abha-error"
                    className="text-sm text-destructive"
                  >
                    {errors.abha_number.message}
                  </p>
                )}
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="patient-department">Department *</Label>
                <select
                  id="patient-department"
                  className={selectClass}
                  aria-invalid={errors.intake_department_id ? true : undefined}
                  aria-describedby={
                    errors.intake_department_id
                      ? "patient-department-error"
                      : undefined
                  }
                  {...departmentField}
                >
                  <option value="">Select consulting department</option>
                  {(departments.data ?? []).map((department) => (
                    <option key={department.id} value={department.id}>
                      {department.name}
                    </option>
                  ))}
                </select>
                {errors.intake_department_id && (
                  <p
                    id="patient-department-error"
                    className="text-sm text-destructive"
                  >
                    {errors.intake_department_id.message}
                  </p>
                )}
                {departments.isError && (
                  <p role="alert" className="text-sm text-destructive">
                    Could not load the OPD departments — retry or register
                    without a queue token later.
                  </p>
                )}
              </div>

              {duplicates.data !== undefined &&
                duplicates.data.warn &&
                duplicates.data.candidates.length > 0 && (
                  <DuplicateWarning
                    candidates={duplicates.data.candidates}
                    acknowledged={acknowledged}
                    onAcknowledgeChange={setAcknowledged}
                  />
                )}
              {duplicates.isError && (
                <p
                  role="alert"
                  className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  The duplicate check could not run. It is advisory — you can
                  still register, and the registry keeps its own record.
                </p>
              )}
              {ackRequired && !acknowledged && (
                <p
                  role="alert"
                  className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  Confirm the possible duplicates first — check the box to
                  register anyway, or open a candidate's record to compare.
                </p>
              )}

              <div className="flex flex-wrap justify-end gap-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={clearForm}
                  disabled={create.isPending}
                >
                  Clear form
                </Button>
                <Button type="submit" disabled={create.isPending}>
                  {create.isPending ? "Registering…" : "Register patient"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>

      <aside className="grid gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Registration guide</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="flex flex-col gap-4">
              {GUIDE_STEPS.map((step, index) => (
                <li key={step.title} className="flex gap-3">
                  <span className="h-fit rounded border border-primary/40 px-1.5 font-mono text-xs text-primary">
                    {`0${index + 1}`}
                  </span>
                  <div className="grid gap-0.5">
                    <p className="text-sm font-semibold text-foreground">
                      {step.title}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {step.detail}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription className="font-mono text-xs uppercase tracking-widest">
              Secure record
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">
              Patient data is prepared for the EMR and available to authorized
              clinical teams. The UHID is minted by the registry when the
              patient is saved — this form never asks for one (REG-001), and
              the duplicate check is advisory (REG-003).
            </p>
          </CardContent>
        </Card>
      </aside>
    </div>
  );
}
