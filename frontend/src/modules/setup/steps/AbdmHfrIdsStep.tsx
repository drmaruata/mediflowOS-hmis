/**
 * Step 4 — ABDM & HFR identifiers. All three identifiers are optional here:
 * onboarding stores them nullable because NHA data is not always at hand
 * (backend services.py, TEN-011), and a hospital must be able to finish the
 * wizard and register later. The payload holds the typed IDs for
 * restoration; nothing is written to the facility row by this step.
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StepFooter, useStepDirtyBridge } from "../components/StepFooter";
import type { StepComponentProps } from "../components/StepFooter";
import {
  extractServerErrors,
  payloadString,
  useSaveSetupStep,
} from "../setup.api";

const schema = z.object({
  abdm_hip_id: z.string(),
  abdm_facility_id: z.string(),
  hfr_id: z.string(),
});

type Values = z.infer<typeof schema>;

const FIELDS = [
  { name: "abdm_hip_id", label: "ABDM HIP ID" },
  { name: "abdm_facility_id", label: "ABDM facility ID" },
  { name: "hfr_id", label: "HFR ID" },
] as const;

export default function AbdmHfrIdsStep({
  step,
  onBack,
  onAdvance,
  onDirtyChange,
  isLast,
}: StepComponentProps) {
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isDirty },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      abdm_hip_id: payloadString(step.payload, "abdm_hip_id"),
      abdm_facility_id: payloadString(step.payload, "abdm_facility_id"),
      hfr_id: payloadString(step.payload, "hfr_id"),
    },
  });
  const save = useSaveSetupStep("abdm_hfr_ids");
  useStepDirtyBridge(isDirty, onDirtyChange);

  const onServerError = (error: unknown) => {
    const { fieldErrors } = extractServerErrors(error);
    for (const field of FIELDS) {
      if (field.name in fieldErrors) {
        setError(field.name, { message: fieldErrors[field.name] });
      }
    }
  };

  const saveDraft = handleSubmit((values) => {
    save.mutate(
      { status: "in_progress", payload: values },
      { onSuccess: () => reset(values), onError: onServerError },
    );
  });
  const complete = handleSubmit((values) => {
    save.mutate(
      { status: "complete", payload: values },
      {
        onSuccess: () => {
          reset(values);
          onAdvance();
        },
        onError: onServerError,
      },
    );
  });

  return (
    <form onSubmit={complete} noValidate className="flex flex-col gap-4">
      {FIELDS.map((field) => {
        const error = errors[field.name];
        return (
          <div key={field.name} className="grid gap-1.5">
            <Label htmlFor={`ids-${field.name}`}>{field.label}</Label>
            <Input
              id={`ids-${field.name}`}
              type="text"
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `ids-${field.name}-error` : undefined}
              {...register(field.name)}
            />
            {error && (
              <p id={`ids-${field.name}-error`} className="text-sm text-destructive">
                {error.message}
              </p>
            )}
          </div>
        );
      })}
      <StepFooter
        onBack={onBack}
        dirty={isDirty}
        onSave={saveDraft}
        saving={save.isPending}
        saved={save.isSuccess}
        error={save.error}
        claim="identity.setup.manage"
        nextLabel={isLast ? "Finish" : "Next"}
      />
    </form>
  );
}
