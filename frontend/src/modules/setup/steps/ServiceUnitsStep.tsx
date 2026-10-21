/**
 * Step 7 — Service units (SET-004 via /service-units/). Same contract as the
 * other table steps: rows live in their own table, the step payload holds a
 * counts summary, and the type choices mirror the model's documented tags
 * (OT, Labour Room, Laboratory…). A unit needs a parent facility.
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ResourceSection } from "../components/ResourceSection";
import { StepFooter, useStepDirtyBridge } from "../components/StepFooter";
import type { StepComponentProps } from "../components/StepFooter";
import {
  createServiceUnit,
  extractServerErrors,
  fetchFacilities,
  fetchServiceUnits,
  useSaveSetupStep,
} from "../setup.api";

const TYPES = [
  "OT",
  "Labour Room",
  "Laboratory",
  "Radiology",
  "Pharmacy",
  "Blood Bank",
  "Mortuary",
  "CSSD",
] as const;

const schema = z.object({
  facility: z.string().uuid("Select the facility."),
  name: z.string().min(2, "Service unit name is required."),
  // The native select only offers TYPES; membership stays server-side.
  type_tag: z.string().min(1, "Select the unit type."),
});

type Values = z.infer<typeof schema>;

const selectClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-invalid:border-destructive";

export default function ServiceUnitsStep({
  onBack,
  onAdvance,
  onDirtyChange,
  isLast,
}: StepComponentProps) {
  const queryClient = useQueryClient();
  const facilities = useQuery({ queryKey: ["facilities"], queryFn: fetchFacilities });
  const serviceUnits = useQuery({
    queryKey: ["service-units"],
    queryFn: fetchServiceUnits,
  });

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { facility: "", name: "", type_tag: "" },
  });

  const addUnit = useMutation({
    mutationFn: createServiceUnit,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["service-units"] });
    },
  });

  const save = useSaveSetupStep("service_units");
  useStepDirtyBridge(form.formState.isDirty, onDirtyChange);

  const counts = { service_units: serviceUnits.data?.count ?? 0 };
  const saveDraft = () => save.mutate({ status: "in_progress", payload: counts });
  const complete = () =>
    save.mutate({ status: "complete", payload: counts }, { onSuccess: onAdvance });

  return (
    <div>
      <ResourceSection
        title="Service units"
        loading={serviceUnits.isPending}
        rows={serviceUnits.data?.results ?? []}
        rowKey={(row) => row.id}
        emptyText="No service units yet."
        columns={[
          { key: "name", header: "Name", render: (row) => row.name },
          { key: "type_tag", header: "Type", render: (row) => row.type_tag },
        ]}
      >
        <form
          className="mt-3"
          noValidate
          onSubmit={form.handleSubmit((values) =>
            addUnit.mutate(values, {
              onSuccess: () => form.reset({ facility: "", name: "", type_tag: "" }),
              onError: (error) => {
                const { fieldErrors } = extractServerErrors(error);
                if ("name" in fieldErrors) form.setError("name", { message: fieldErrors.name });
                if ("facility" in fieldErrors) {
                  form.setError("facility", { message: fieldErrors.facility });
                }
                if ("type_tag" in fieldErrors) {
                  form.setError("type_tag", { message: fieldErrors.type_tag });
                }
              },
            }),
          )}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor="unit-facility">Facility</Label>
              <select
                id="unit-facility"
                className={selectClass}
                aria-invalid={form.formState.errors.facility ? true : undefined}
                aria-describedby={
                  form.formState.errors.facility ? "unit-facility-error" : undefined
                }
                {...form.register("facility")}
              >
                <option value="">Select facility…</option>
                {(facilities.data?.results ?? []).map((facility) => (
                  <option key={facility.id} value={facility.id}>
                    {facility.name}
                  </option>
                ))}
              </select>
              {form.formState.errors.facility && (
                <p id="unit-facility-error" className="text-sm text-destructive">
                  {form.formState.errors.facility.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="unit-name">Service unit name</Label>
              <Input
                id="unit-name"
                type="text"
                aria-invalid={form.formState.errors.name ? true : undefined}
                aria-describedby={form.formState.errors.name ? "unit-name-error" : undefined}
                {...form.register("name")}
              />
              {form.formState.errors.name && (
                <p id="unit-name-error" className="text-sm text-destructive">
                  {form.formState.errors.name.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="unit-type">Unit type</Label>
              <select
                id="unit-type"
                className={selectClass}
                aria-invalid={form.formState.errors.type_tag ? true : undefined}
                {...form.register("type_tag")}
              >
                <option value="">Select type…</option>
                {TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
              {form.formState.errors.type_tag && (
                <p className="text-sm text-destructive">
                  {form.formState.errors.type_tag.message}
                </p>
              )}
            </div>
          </div>
          <Button type="submit" variant="outline" className="mt-3" disabled={addUnit.isPending}>
            Add service unit
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
