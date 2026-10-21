/**
 * Step 10 — Indicator baseline inputs (SET-007 via /baseline-inputs/): the
 * manual values the wizard files per indicator source code and reporting
 * period. The client mirrors the server's one validation rule — negative
 * values are refused (the backend serializer does the same) — and the
 * period accepts the model's documented month (2026-10) or year (2026)
 * shape. The doc's "inputs follow indicator applicability" rule needs the
 * Quality OS catalogue (R3), which no endpoint here exposes yet, so it is
 * honestly deferred. Writes are gated on identity.baseline_input.write.
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ResourceSection } from "../components/ResourceSection";
import { StepAlert, StepFooter, useStepDirtyBridge } from "../components/StepFooter";
import type { StepComponentProps } from "../components/StepFooter";
import {
  createBaselineInput,
  extractServerErrors,
  fetchBaselineInputs,
  useSaveSetupStep,
} from "../setup.api";

const schema = z.object({
  indicator_source_code: z.string().min(1, "Indicator source code is required."),
  period: z
    .string()
    .regex(/^\d{4}(-\d{2})?$/, "Use a month (2026-10) or a year (2026)."),
  value: z
    .number({ invalid_type_error: "Value is required." })
    .min(0, "Baseline values cannot be negative."),
});

type Values = z.infer<typeof schema>;

export default function IndicatorsBaselineStep({
  onBack,
  onAdvance,
  onDirtyChange,
  isLast,
}: StepComponentProps) {
  const queryClient = useQueryClient();
  const baselineInputs = useQuery({
    queryKey: ["baseline-inputs"],
    queryFn: fetchBaselineInputs,
  });

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      indicator_source_code: "",
      period: "",
      value: Number.NaN,
    },
  });

  const addRow = useMutation({
    mutationFn: createBaselineInput,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["baseline-inputs"] });
    },
  });

  const save = useSaveSetupStep("indicators_baseline");
  useStepDirtyBridge(form.formState.isDirty, onDirtyChange);

  const counts = { baseline_inputs: baselineInputs.data?.count ?? 0 };
  const saveDraft = () => save.mutate({ status: "in_progress", payload: counts });
  const complete = () =>
    save.mutate({ status: "complete", payload: counts }, { onSuccess: onAdvance });

  return (
    <div>
      <ResourceSection
        title="Baseline inputs"
        loading={baselineInputs.isPending}
        rows={baselineInputs.data?.results ?? []}
        rowKey={(row) => row.id}
        emptyText="No baseline inputs yet."
        columns={[
          {
            key: "indicator_source_code",
            header: "Indicator",
            render: (row) => row.indicator_source_code,
          },
          { key: "period", header: "Period", render: (row) => row.period },
          { key: "value", header: "Value", render: (row) => row.value },
          { key: "source", header: "Source", render: (row) => row.source },
        ]}
      >
        <StepAlert error={addRow.error} claim="identity.baseline_input.write" />
        <form
          className="mt-3"
          noValidate
          onSubmit={form.handleSubmit((values) =>
            addRow.mutate(values, {
              onSuccess: () =>
                form.reset({ indicator_source_code: "", period: "", value: Number.NaN }),
              onError: (error) => {
                const { fieldErrors } = extractServerErrors(error);
                if ("indicator_source_code" in fieldErrors) {
                  form.setError("indicator_source_code", {
                    message: fieldErrors.indicator_source_code,
                  });
                }
                if ("period" in fieldErrors) {
                  form.setError("period", { message: fieldErrors.period });
                }
                if ("value" in fieldErrors) {
                  form.setError("value", { message: fieldErrors.value });
                }
              },
            }),
          )}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor="baseline-indicator">Indicator source code</Label>
              <Input
                id="baseline-indicator"
                type="text"
                aria-invalid={form.formState.errors.indicator_source_code ? true : undefined}
                aria-describedby={
                  form.formState.errors.indicator_source_code
                    ? "baseline-indicator-error"
                    : undefined
                }
                {...form.register("indicator_source_code")}
              />
              {form.formState.errors.indicator_source_code && (
                <p id="baseline-indicator-error" className="text-sm text-destructive">
                  {form.formState.errors.indicator_source_code.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="baseline-period">Period</Label>
              <Input
                id="baseline-period"
                type="text"
                placeholder="2026-10"
                aria-invalid={form.formState.errors.period ? true : undefined}
                aria-describedby={
                  form.formState.errors.period ? "baseline-period-error" : undefined
                }
                {...form.register("period")}
              />
              {form.formState.errors.period && (
                <p id="baseline-period-error" className="text-sm text-destructive">
                  {form.formState.errors.period.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="baseline-value">Value</Label>
              <Input
                id="baseline-value"
                type="number"
                aria-invalid={form.formState.errors.value ? true : undefined}
                aria-describedby={
                  form.formState.errors.value ? "baseline-value-error" : undefined
                }
                {...form.register("value", { valueAsNumber: true })}
              />
              {form.formState.errors.value && (
                <p id="baseline-value-error" className="text-sm text-destructive">
                  {form.formState.errors.value.message}
                </p>
              )}
            </div>
          </div>
          <Button type="submit" variant="outline" className="mt-3" disabled={addRow.isPending}>
            Add baseline input
          </Button>
        </form>
      </ResourceSection>
      <StepFooter
        onBack={onBack}
        dirty={form.formState.isDirty}
        onSave={saveDraft}
        saving={save.isPending}
        saved={save.isSuccess}
        error={save.error}
        claim="identity.setup.manage"
        nextLabel={isLast ? "Finish" : "Next"}
        onNext={complete}
      />
    </div>
  );
}
