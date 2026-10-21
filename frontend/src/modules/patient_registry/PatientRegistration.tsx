/**
 * PatientRegistration — the counter's new-patient form (REG-001, REG-003,
 * REG-005, REG-007; UI_UX §7 "Patient registry — search/register").
 *
 * Three keyboard-first sections (UI-002): Enter submits the section in
 * focus, a failing section focuses its first invalid field (RHF's trigger
 * shouldFocus), and a valid section moves focus to the next one's first
 * field; the last section's Enter registers the patient.
 *
 * The UHID is minted by the server (REG-001) — no UHID field exists here
 * and only the create response's identifier is ever rendered. The duplicate
 * check (REG-003) runs on blur of the name/DOB/mobile fields and is
 * advisory: "register anyway" needs an explicit checkbox, and the create
 * itself is the server's to accept or refuse. An age-only candidate sends
 * no birth key — the check API matches on dob, and inventing a year from an
 * approximate age would silently narrow what the server compares.
 */

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSession } from "@/lib/session";
import { extractServerErrors } from "@/lib/serverErrors";
import { DuplicateWarning } from "./DuplicateWarning";
import {
  buildRegistrationPayload,
  createPatient,
  duplicateCheck,
  fetchOpdDepartments,
  isValidIndianMobile,
} from "./patient.api";
import type { DuplicateCheckInput } from "./patient.api";

const GENDERS = ["male", "female", "other"] as const;

const registrationSchema = z
  .object({
    name: z
      .string()
      .trim()
      .min(2, "Enter the patient's full name.")
      .max(200, "The name is too long (max 200 characters)."),
    gender: z.string().min(1, "Select a gender."),
    dob: z.string(),
    age_years: z.string(),
    mobile: z.string(),
    abha_number: z.string(),
    intake_department_id: z.string().min(1, "Select the OP intake department."),
  })
  .superRefine((values, ctx) => {
    if (values.dob === "" && values.age_years === "") {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["dob"],
        message: "Enter a date of birth or an approximate age.",
      });
    }
    if (values.age_years !== "" && !/^\d{1,3}$/.test(values.age_years)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["age_years"],
        message: "Enter an age in years (digits only).",
      });
    }
    if (values.mobile.trim() !== "" && !isValidIndianMobile(values.mobile)) {
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

const IDENTITY_FIELDS = ["name", "gender", "dob", "age_years"] as const;
const CONTACT_FIELDS = ["mobile", "abha_number"] as const;

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
      age_years: "",
      mobile: "",
      abha_number: "",
      intake_department_id: "",
    },
  });
  const { register, handleSubmit, trigger, getValues, setError, reset } = form;
  const errors = form.formState.errors;

  const [acknowledged, setAcknowledged] = useState(false);
  const [ackRequired, setAckRequired] = useState(false);

  const mobileRef = useRef<HTMLInputElement | null>(null);
  const departmentRef = useRef<HTMLSelectElement | null>(null);
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
  // demographics/contact refusals have no single form field: surface them
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

  const submitIdentity = async (event: FormEvent) => {
    event.preventDefault();
    if (await trigger([...IDENTITY_FIELDS], { shouldFocus: true })) {
      mobileRef.current?.focus();
    }
  };

  const submitContact = async (event: FormEvent) => {
    event.preventDefault();
    if (await trigger([...CONTACT_FIELDS], { shouldFocus: true })) {
      departmentRef.current?.focus();
    }
  };

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

  const nameField = register("name", { onBlur: runDuplicateCheck });
  const dobField = register("dob", { onBlur: runDuplicateCheck });
  const ageField = register("age_years", { onBlur: runDuplicateCheck });
  const mobileField = register("mobile", { onBlur: runDuplicateCheck });
  const abhaField = register("abha_number", { onBlur: runDuplicateCheck });
  const genderField = register("gender");
  const departmentField = register("intake_department_id");

  if (create.isSuccess && create.data !== undefined) {
    const patient = create.data;
    return (
      <div>
        <h1 className="text-xl font-bold tracking-tight text-card-foreground">
          Patient registered
        </h1>
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
            OP slip printing is not built yet — the print screen lands with the
            next release task. The token above is live in the OPD queue.
          </p>
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button asChild>
            <Link to={`/patients/${patient.id}`}>Open patient record</Link>
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              reset();
              create.reset();
              duplicates.reset();
              lastProbe.current = "";
            }}
          >
            Register another patient
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-xl font-bold tracking-tight text-card-foreground">
        New patient
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        The registry issues the UHID when the patient is saved — this form
        never asks for one (REG-001).
      </p>

      {failureText !== null && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {failureText}
        </p>
      )}

      <section aria-label="Identity" className="mt-6">
        <h2 className="text-base font-semibold text-card-foreground">Identity</h2>
        <p className="text-xs text-muted-foreground">
          Enter submits this section and moves to contact details.
        </p>
        <form onSubmit={submitIdentity} noValidate className="mt-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="patient-name">Patient name</Label>
              <Input
                id="patient-name"
                type="text"
                autoComplete="off"
                aria-invalid={errors.name ? true : undefined}
                aria-describedby={errors.name ? "patient-name-error" : undefined}
                {...nameField}
              />
              {errors.name && (
                <p id="patient-name-error" className="text-sm text-destructive">
                  {errors.name.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="patient-gender">Gender</Label>
              <select
                id="patient-gender"
                className={selectClass}
                aria-invalid={errors.gender ? true : undefined}
                aria-describedby={errors.gender ? "patient-gender-error" : undefined}
                {...genderField}
              >
                <option value="">Select gender…</option>
                {GENDERS.map((gender) => (
                  <option key={gender} value={gender}>
                    {gender.charAt(0).toUpperCase() + gender.slice(1)}
                  </option>
                ))}
              </select>
              {errors.gender && (
                <p id="patient-gender-error" className="text-sm text-destructive">
                  {errors.gender.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="patient-dob">Date of birth</Label>
              <Input
                id="patient-dob"
                type="date"
                aria-invalid={errors.dob ? true : undefined}
                aria-describedby={errors.dob ? "patient-dob-error" : undefined}
                {...dobField}
              />
              {errors.dob && (
                <p id="patient-dob-error" className="text-sm text-destructive">
                  {errors.dob.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="patient-age">Approximate age (years)</Label>
              <Input
                id="patient-age"
                type="text"
                inputMode="numeric"
                placeholder="If the date of birth is unknown"
                aria-invalid={errors.age_years ? true : undefined}
                aria-describedby={errors.age_years ? "patient-age-error" : undefined}
                {...ageField}
              />
              {errors.age_years && (
                <p id="patient-age-error" className="text-sm text-destructive">
                  {errors.age_years.message}
                </p>
              )}
            </div>
          </div>
        </form>
      </section>

      <section aria-label="Contact and ABHA" className="mt-6">
        <h2 className="text-base font-semibold text-card-foreground">
          Contact & ABHA
        </h2>
        <p className="text-xs text-muted-foreground">
          Enter submits this section and moves to the OP intake department.
        </p>
        <form onSubmit={submitContact} noValidate className="mt-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="patient-mobile">Mobile number</Label>
              <Input
                id="patient-mobile"
                type="tel"
                autoComplete="off"
                aria-invalid={errors.mobile ? true : undefined}
                aria-describedby={errors.mobile ? "patient-mobile-error" : undefined}
                {...mobileField}
                ref={(element) => {
                  mobileField.ref(element);
                  mobileRef.current = element;
                }}
              />
              {errors.mobile && (
                <p id="patient-mobile-error" className="text-sm text-destructive">
                  {errors.mobile.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
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
                <p id="patient-abha-error" className="text-sm text-destructive">
                  {errors.abha_number.message}
                </p>
              )}
            </div>
          </div>
        </form>
      </section>

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
          className="mt-4 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          The duplicate check could not run. It is advisory — you can still
          register, and the registry keeps its own record.
        </p>
      )}

      <section aria-label="OP intake" className="mt-6">
        <h2 className="text-base font-semibold text-card-foreground">
          OP intake
        </h2>
        <p className="text-xs text-muted-foreground">
          Enter registers the patient and issues the UHID and queue token.
        </p>
        <form onSubmit={submitRegistration} noValidate className="mt-3">
          <div className="grid gap-1.5 sm:max-w-md">
            <Label htmlFor="patient-department">OP intake department</Label>
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
              ref={(element) => {
                departmentField.ref(element);
                departmentRef.current = element;
              }}
            >
              <option value="">Select department…</option>
              {(departments.data ?? []).map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </select>
            {errors.intake_department_id && (
              <p id="patient-department-error" className="text-sm text-destructive">
                {errors.intake_department_id.message}
              </p>
            )}
            {departments.isError && (
              <p role="alert" className="text-sm text-destructive">
                Could not load the OPD departments — retry or register without a
                queue token later.
              </p>
            )}
          </div>
          {ackRequired && !acknowledged && (
            <p
              role="alert"
              className="mt-3 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              Confirm the possible duplicates first — check the box to register
              anyway, or open a candidate's record to compare.
            </p>
          )}
          <Button
            type="submit"
            className="mt-3"
            disabled={create.isPending}
          >
            {create.isPending ? "Registering…" : "Register patient"}
          </Button>
        </form>
      </section>
    </div>
  );
}
