/**
 * Step 8 — Staff positions (SET-005 via /staff-positions/). Sanctioned and
 * in-position counts are non-negative integers client-side; the doc's
 * "staff designation required" rule is the schema's required designation,
 * and the department parent is a required select. Payload is a counts
 * summary like the other table steps.
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
  createStaffPosition,
  extractServerErrors,
  fetchAllDepartments,
  fetchStaffPositions,
  useSaveSetupStep,
} from "../setup.api";

const schema = z.object({
  department: z.string().uuid("Select the department."),
  designation: z.string().min(2, "Designation is required."),
  specialty: z.string(),
  sanctioned: z
    .number({ invalid_type_error: "Sanctioned count is required." })
    .int("Sanctioned must be a whole number.")
    .min(0, "Sanctioned cannot be negative."),
  in_position: z
    .number({ invalid_type_error: "In-position count is required." })
    .int("In-position must be a whole number.")
    .min(0, "In position cannot be negative."),
});

type Values = z.infer<typeof schema>;

const selectClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-invalid:border-destructive";

export default function StaffPositionsStep({
  onBack,
  onAdvance,
  onDirtyChange,
  isLast,
}: StepComponentProps) {
  const queryClient = useQueryClient();
  // Fetch-all, not the paginated list: departments here are only a join
  // source and a select feed, so a department past page 1 must still
  // resolve by name and stay selectable.
  const departments = useQuery({
    queryKey: ["departments", "all"],
    queryFn: fetchAllDepartments,
  });
  const staffPositions = useQuery({
    queryKey: ["staff-positions"],
    queryFn: fetchStaffPositions,
  });

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      department: "",
      designation: "",
      specialty: "",
      sanctioned: 0,
      in_position: 0,
    },
  });

  const addPosition = useMutation({
    mutationFn: createStaffPosition,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["staff-positions"] });
    },
  });

  const save = useSaveSetupStep("staff_positions");
  useStepDirtyBridge(form.formState.isDirty, onDirtyChange);

  const counts = { staff_positions: staffPositions.data?.count ?? 0 };
  const saveDraft = () => save.mutate({ status: "in_progress", payload: counts });
  const complete = () =>
    save.mutate({ status: "complete", payload: counts }, { onSuccess: onAdvance });

  const departmentNames = new Map((departments.data ?? []).map((row) => [row.id, row.name]));

  return (
    <div>
      <ResourceSection
        title="Staff positions"
        loading={staffPositions.isPending}
        rows={staffPositions.data?.results ?? []}
        rowKey={(row) => row.id}
        emptyText="No staff positions yet."
        totalCount={staffPositions.data?.count ?? null}
        columns={[
          { key: "designation", header: "Designation", render: (row) => row.designation },
          { key: "specialty", header: "Specialty", render: (row) => row.specialty ?? "—" },
          {
            key: "department",
            header: "Department",
            render: (row) => departmentNames.get(row.department) ?? row.department,
          },
          { key: "sanctioned", header: "Sanctioned", render: (row) => row.sanctioned },
          { key: "in_position", header: "In position", render: (row) => row.in_position },
        ]}
      >
        <StepAlert error={addPosition.error} />
        <form
          className="mt-3"
          noValidate
          onSubmit={form.handleSubmit((values) =>
            addPosition.mutate(values, {
              onSuccess: () =>
                form.reset({
                  department: "",
                  designation: "",
                  specialty: "",
                  sanctioned: 0,
                  in_position: 0,
                }),
              onError: (error) => {
                const { fieldErrors } = extractServerErrors(error);
                if ("designation" in fieldErrors) {
                  form.setError("designation", { message: fieldErrors.designation });
                }
                if ("department" in fieldErrors) {
                  form.setError("department", { message: fieldErrors.department });
                }
                if ("sanctioned" in fieldErrors) {
                  form.setError("sanctioned", { message: fieldErrors.sanctioned });
                }
                if ("in_position" in fieldErrors) {
                  form.setError("in_position", { message: fieldErrors.in_position });
                }
              },
            }),
          )}
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor="position-department">Department</Label>
              <select
                id="position-department"
                className={selectClass}
                aria-invalid={form.formState.errors.department ? true : undefined}
                aria-describedby={
                  form.formState.errors.department ? "position-department-error" : undefined
                }
                {...form.register("department")}
              >
                <option value="">Select department…</option>
                {(departments.data ?? []).map((department) => (
                  <option key={department.id} value={department.id}>
                    {department.name}
                  </option>
                ))}
              </select>
              {form.formState.errors.department && (
                <p id="position-department-error" className="text-sm text-destructive">
                  {form.formState.errors.department.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="position-designation">Designation</Label>
              <Input
                id="position-designation"
                type="text"
                aria-invalid={form.formState.errors.designation ? true : undefined}
                aria-describedby={
                  form.formState.errors.designation ? "position-designation-error" : undefined
                }
                {...form.register("designation")}
              />
              {form.formState.errors.designation && (
                <p id="position-designation-error" className="text-sm text-destructive">
                  {form.formState.errors.designation.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="position-specialty">Specialty (optional)</Label>
              <Input id="position-specialty" type="text" {...form.register("specialty")} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="position-sanctioned">Sanctioned</Label>
              <Input
                id="position-sanctioned"
                type="number"
                aria-invalid={form.formState.errors.sanctioned ? true : undefined}
                aria-describedby={
                  form.formState.errors.sanctioned ? "position-sanctioned-error" : undefined
                }
                {...form.register("sanctioned", { valueAsNumber: true })}
              />
              {form.formState.errors.sanctioned && (
                <p id="position-sanctioned-error" className="text-sm text-destructive">
                  {form.formState.errors.sanctioned.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="position-in-position">In position</Label>
              <Input
                id="position-in-position"
                type="number"
                aria-invalid={form.formState.errors.in_position ? true : undefined}
                aria-describedby={
                  form.formState.errors.in_position ? "position-in-position-error" : undefined
                }
                {...form.register("in_position", { valueAsNumber: true })}
              />
              {form.formState.errors.in_position && (
                <p id="position-in-position-error" className="text-sm text-destructive">
                  {form.formState.errors.in_position.message}
                </p>
              )}
            </div>
          </div>
          <Button type="submit" variant="outline" className="mt-3" disabled={addPosition.isPending}>
            Add position
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
