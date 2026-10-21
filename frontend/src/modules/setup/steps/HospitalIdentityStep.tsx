/**
 * Step 1 — Hospital identity (SET-001). The payload holds the form's own
 * values (`{name}`), matching the shape the backend's wizard tests use for
 * this step, so a resumed session restores what was typed (SET-008).
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  StepFooter,
  useStepDirtyBridge,
} from "../components/StepFooter";
import type { StepComponentProps } from "../components/StepFooter";
import {
  extractServerErrors,
  payloadString,
  useSaveSetupStep,
} from "../setup.api";

const schema = z.object({
  name: z.string().min(2, "Hospital name is required (min 2 characters)."),
});

type Values = z.infer<typeof schema>;

export default function HospitalIdentityStep({
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
    defaultValues: { name: payloadString(step.payload, "name") },
  });
  const save = useSaveSetupStep("hospital_identity");
  useStepDirtyBridge(isDirty, onDirtyChange);

  const onServerError = (error: unknown) => {
    const { fieldErrors } = extractServerErrors(error);
    if ("name" in fieldErrors) setError("name", { message: fieldErrors.name });
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
        <Label htmlFor="hospital-name">Hospital name</Label>
        <Input
          id="hospital-name"
          type="text"
          autoComplete="organization"
          aria-invalid={errors.name ? true : undefined}
          aria-describedby={errors.name ? "hospital-name-error" : undefined}
          {...register("name")}
        />
        {errors.name && (
          <p id="hospital-name-error" className="text-sm text-destructive">
            {errors.name.message}
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
