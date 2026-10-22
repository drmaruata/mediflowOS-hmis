/**
 * Step 5 — Accreditation profile. The profiles mirror Tenant's
 * accreditation_profile examples (NQAS/NABH codes); none selected is valid —
 * a hospital may finish setup pre-accreditation. The payload holds the
 * selection (`{profiles}`) for restoration. The doc's "Quality OS
 * applicability" validation lands with the Quality OS catalogue (R3); no
 * applicability endpoint exists for this wizard to validate against yet.
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { Label } from "@/components/ui/label";
import { StepFooter, useStepDirtyBridge } from "../components/StepFooter";
import type { StepComponentProps } from "../components/StepFooter";
import {
  payloadStringList,
  useSaveSetupStep,
} from "../setup.api";

const PROFILES = ["NQAS-DH", "NQAS-CHC", "NQAS-PHC", "NABH-6", "NABH-SH"] as const;

const schema = z.object({
  // Only the checkboxes' own values can arrive here; the client enforces
  // nothing beyond shape and the payload stays a plain string list.
  profiles: z.array(z.string()),
});

type Values = z.infer<typeof schema>;

export default function AccreditationStep({
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
    formState: { isDirty },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { profiles: payloadStringList(step.payload, "profiles") },
  });
  const save = useSaveSetupStep("accreditation");
  useStepDirtyBridge(isDirty, onDirtyChange);

  const saveDraft = handleSubmit((values) => {
    save.mutate(
      { status: "in_progress", payload: values },
      { onSuccess: () => reset(values) },
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
      },
    );
  });

  return (
    <form onSubmit={complete} noValidate className="flex flex-col gap-4">
      <fieldset className="grid gap-2">
        <legend className="text-sm font-medium text-foreground">
          Accreditation profiles
        </legend>
        {PROFILES.map((profile) => (
          <div key={profile} className="flex items-center gap-2">
            <input
              id={`profile-${profile}`}
              type="checkbox"
              value={profile}
              className="size-4 rounded border-input accent-primary"
              {...register("profiles")}
            />
            <Label htmlFor={`profile-${profile}`}>{profile}</Label>
          </div>
        ))}
      </fieldset>
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
