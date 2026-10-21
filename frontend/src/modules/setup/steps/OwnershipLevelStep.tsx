/**
 * Step 2 — Ownership level. The facility's level (District Hospital, CHC,
 * PHC…) is stored on the facility row by onboarding; this step records the
 * wizard's value in its payload (`{facility_level}`) for restoration, and a
 * native select keeps the choice keyboard-reachable (the doc's Select
 * component is not vendored — UI_UX §7 composition, AGENTS §5).
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { Label } from "@/components/ui/label";
import { StepFooter, useStepDirtyBridge } from "../components/StepFooter";
import type { StepComponentProps } from "../components/StepFooter";
import {
  extractServerErrors,
  payloadString,
  useSaveSetupStep,
} from "../setup.api";

const LEVELS = [
  "District Hospital",
  "Sub-District Hospital",
  "Community Health Centre",
  "Primary Health Centre",
  "Health & Wellness Centre",
  "Teaching Hospital",
] as const;

const schema = z.object({
  // The native select only offers LEVELS, so the client just enforces a
  // choice; membership in the list is the server's authority (AGENTS §5).
  facility_level: z.string().min(1, "Select the facility level."),
});

type Values = z.infer<typeof schema>;

export default function OwnershipLevelStep({
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
    defaultValues: { facility_level: payloadString(step.payload, "facility_level") },
  });
  const save = useSaveSetupStep("ownership_level");
  useStepDirtyBridge(isDirty, onDirtyChange);

  const onServerError = (error: unknown) => {
    const { fieldErrors } = extractServerErrors(error);
    if ("facility_level" in fieldErrors) {
      setError("facility_level", { message: fieldErrors.facility_level });
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
      <div className="grid gap-1.5">
        <Label htmlFor="facility-level">Facility level</Label>
        <select
          id="facility-level"
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-invalid:border-destructive"
          aria-invalid={errors.facility_level ? true : undefined}
          aria-describedby={errors.facility_level ? "facility-level-error" : undefined}
          {...register("facility_level")}
        >
          <option value="">Select the facility level…</option>
          {LEVELS.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
        {errors.facility_level && (
          <p id="facility-level-error" className="text-sm text-destructive">
            {errors.facility_level.message}
          </p>
        )}
      </div>
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
