/**
 * Step 9 — Reference data (SET-006 via /reference-data/): the indicator
 * denominators — catchment population, ambulances, essential commodities.
 * The row's `value` JSON differs per kind, so the form collects one number
 * and stores it in the shape the backend's own tests use:
 * {population} for catchment, {count} otherwise. Writes are gated on
 * identity.reference_data.write, so the step's row mutations name that
 * claim in a 403. Payload is a counts summary like the other table steps.
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ResourceSection } from "@/components/ResourceSection";
import { StepAlert, StepFooter, useStepDirtyBridge } from "../components/StepFooter";
import type { StepComponentProps } from "../components/StepFooter";
import {
  createReferenceData,
  extractServerErrors,
  fetchReferenceData,
  useSaveSetupStep,
} from "../setup.api";

const KINDS = [
  { value: "catchment_population", label: "Catchment population" },
  { value: "ambulance", label: "Ambulance" },
  { value: "essential_commodity", label: "Essential commodity" },
] as const;

const schema = z.object({
  // The native select only offers the three kinds; membership stays
  // server-side (the model's choices).
  kind: z.string().min(1, "Select the kind."),
  key: z.string().min(1, "Key is required."),
  value: z
    .number({ invalid_type_error: "Value is required." })
    .min(0, "Value cannot be negative."),
});

type Values = z.infer<typeof schema>;

const selectClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-invalid:border-destructive";

export default function ReferenceDataStep({
  onBack,
  onAdvance,
  onDirtyChange,
  isLast,
}: StepComponentProps) {
  const queryClient = useQueryClient();
  const referenceData = useQuery({
    queryKey: ["reference-data"],
    queryFn: fetchReferenceData,
  });

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { kind: "", key: "", value: Number.NaN },
  });

  const addRow = useMutation({
    mutationFn: (values: Values) =>
      createReferenceData({
        kind: values.kind,
        key: values.key,
        value:
          values.kind === "catchment_population"
            ? { population: values.value }
            : { count: values.value },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["reference-data"] });
    },
  });

  const save = useSaveSetupStep("reference_data");
  useStepDirtyBridge(form.formState.isDirty, onDirtyChange);

  const counts = { reference_data_rows: referenceData.data?.count ?? 0 };
  const saveDraft = () => save.mutate({ status: "in_progress", payload: counts });
  const complete = () =>
    save.mutate({ status: "complete", payload: counts }, { onSuccess: onAdvance });

  return (
    <div>
      <ResourceSection
        title="Reference data"
        loading={referenceData.isPending}
        rows={referenceData.data?.results ?? []}
        rowKey={(row) => row.id}
        emptyText="No reference data yet."
        totalCount={referenceData.data?.count ?? null}
        columns={[
          { key: "kind", header: "Kind", render: (row) => row.kind },
          { key: "key", header: "Key", render: (row) => row.key },
          { key: "value", header: "Value", render: (row) => JSON.stringify(row.value) },
          { key: "active", header: "Active", render: (row) => (row.active ? "Yes" : "No") },
        ]}
      >
        <StepAlert error={addRow.error} claim="identity.reference_data.write" />
        <form
          className="mt-3"
          noValidate
          onSubmit={form.handleSubmit((values) =>
            addRow.mutate(values, {
              onSuccess: () => form.reset({ kind: "", key: "", value: Number.NaN }),
              onError: (error) => {
                const { fieldErrors } = extractServerErrors(error);
                if ("kind" in fieldErrors) form.setError("kind", { message: fieldErrors.kind });
                if ("key" in fieldErrors) form.setError("key", { message: fieldErrors.key });
                if ("value" in fieldErrors) {
                  form.setError("value", { message: fieldErrors.value });
                }
              },
            }),
          )}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor="reference-kind">Kind</Label>
              <select
                id="reference-kind"
                className={selectClass}
                aria-invalid={form.formState.errors.kind ? true : undefined}
                aria-describedby={form.formState.errors.kind ? "reference-kind-error" : undefined}
                {...form.register("kind")}
              >
                <option value="">Select kind…</option>
                {KINDS.map((kind) => (
                  <option key={kind.value} value={kind.value}>
                    {kind.label}
                  </option>
                ))}
              </select>
              {form.formState.errors.kind && (
                <p id="reference-kind-error" className="text-sm text-destructive">
                  {form.formState.errors.kind.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="reference-key">Key</Label>
              <Input
                id="reference-key"
                type="text"
                aria-invalid={form.formState.errors.key ? true : undefined}
                aria-describedby={form.formState.errors.key ? "reference-key-error" : undefined}
                {...form.register("key")}
              />
              {form.formState.errors.key && (
                <p id="reference-key-error" className="text-sm text-destructive">
                  {form.formState.errors.key.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="reference-value">Value</Label>
              <Input
                id="reference-value"
                type="number"
                aria-invalid={form.formState.errors.value ? true : undefined}
                aria-describedby={
                  form.formState.errors.value ? "reference-value-error" : undefined
                }
                {...form.register("value", { valueAsNumber: true })}
              />
              {form.formState.errors.value && (
                <p id="reference-value-error" className="text-sm text-destructive">
                  {form.formState.errors.value.message}
                </p>
              )}
            </div>
          </div>
          <Button type="submit" variant="outline" className="mt-3" disabled={addRow.isPending}>
            Add reference row
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
