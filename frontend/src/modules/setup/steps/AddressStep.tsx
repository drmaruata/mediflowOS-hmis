/**
 * Step 3 — Facility address. The payload holds the typed address
 * (`{line1, line2, city, state, pincode}`) so a resumed session restores it;
 * PIN code is validated as a 6-digit Indian postal code client-side only —
 * the server stays the authority on every field.
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
  line1: z.string().min(2, "Address line 1 is required."),
  line2: z.string(),
  city: z.string().min(2, "City is required."),
  state: z.string().min(2, "State is required."),
  pincode: z.string().regex(/^\d{6}$/, "PIN code must be 6 digits."),
});

type Values = z.infer<typeof schema>;

const FIELDS = [
  { name: "line1", label: "Address line 1", autoComplete: "address-line1" },
  { name: "line2", label: "Address line 2 (optional)", autoComplete: "address-line2" },
  { name: "city", label: "City", autoComplete: "address-level2" },
  { name: "state", label: "State", autoComplete: "address-level1" },
  { name: "pincode", label: "PIN code", autoComplete: "postal-code" },
] as const;

export default function AddressStep({
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
      line1: payloadString(step.payload, "line1"),
      line2: payloadString(step.payload, "line2"),
      city: payloadString(step.payload, "city"),
      state: payloadString(step.payload, "state"),
      pincode: payloadString(step.payload, "pincode"),
    },
  });
  const save = useSaveSetupStep("address");
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
            <Label htmlFor={`address-${field.name}`}>{field.label}</Label>
            <Input
              id={`address-${field.name}`}
              type="text"
              autoComplete={field.autoComplete}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `address-${field.name}-error` : undefined}
              {...register(field.name)}
            />
            {error && (
              <p id={`address-${field.name}-error`} className="text-sm text-destructive">
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
