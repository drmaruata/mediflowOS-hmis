/**
 * Step 6 — Departments, wards & beds (SET-002/SET-003 via the config
 * endpoints). Rows live in their own tables behind their own CRUD
 * endpoints, so this step stores only a counts summary in its payload when
 * the step is saved or finished — the rows are the restorable state and the
 * status flag is what the spine restores. Tables compose the shared
 * ResourceSection; parent names are joined client-side from the page-walking
 * fetch-all lists (the serializers expose FK ids, not names), so a parent
 * past the backend's fixed 50-row page still resolves by name.
 *
 * Each add-form is its own <form>, so Enter adds the row in focus instead
 * of finishing the step — the step has no outer form, and its Next is a
 * plain button (see StepFooter). Validation mirrors the doc's rules: a
 * department needs a parent facility, a ward a parent department, a bed a
 * parent ward — each a required select. Duplicate department names (over
 * the full list, via the fetch-all) and bed codes within a ward (over the
 * loaded page only) are pre-checked client-side and render a field error
 * without posting; the backend itself enforces no uniqueness — a
 * documented gap, so duplicates remain creatable through the API and
 * UI_UX §7's uniqueness rule is unenforced server-side.
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
  createBed,
  createDepartment,
  createWard,
  extractServerErrors,
  fetchAllDepartments,
  fetchAllWards,
  fetchBeds,
  fetchDepartments,
  fetchFacilities,
  fetchWards,
  useSaveSetupStep,
} from "../setup.api";

const WARD_TYPES = [
  "Medical",
  "Surgical",
  "Maternity",
  "Paediatric",
  "ICU",
  "SNCU",
  "NRC",
] as const;

const today = () => new Date().toLocaleDateString("en-CA");

const departmentSchema = z.object({
  facility: z.string().uuid("Select the facility."),
  name: z.string().min(2, "Department name is required."),
  effective_from: z.string().min(1, "Effective date is required."),
  opd_enabled: z.boolean(),
  ipd_enabled: z.boolean(),
});

const wardSchema = z.object({
  department: z.string().uuid("Select the department."),
  name: z.string().min(2, "Ward name is required."),
  // The native select only offers WARD_TYPES; list membership stays the
  // server's authority (AGENTS §5).
  type_tag: z.string().min(1, "Select the ward type."),
});

const bedSchema = z.object({
  ward: z.string().uuid("Select the ward."),
  bed_number: z.string().min(1, "Bed number is required."),
});

type DepartmentValues = z.infer<typeof departmentSchema>;
type WardValues = z.infer<typeof wardSchema>;
type BedValues = z.infer<typeof bedSchema>;

const selectClass =
  "flex h-10 w-full rounded-md border border-input bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-invalid:border-destructive";

export default function DepartmentsWardsBedsStep({
  onBack,
  onAdvance,
  onDirtyChange,
  isLast,
}: StepComponentProps) {
  const queryClient = useQueryClient();
  const facilities = useQuery({ queryKey: ["facilities"], queryFn: fetchFacilities });
  const departments = useQuery({ queryKey: ["departments"], queryFn: fetchDepartments });
  // Join sources, not table feeds: they walk every page so a parent past
  // page 1 resolves by name; the tables above stay single-page with a
  // visible caption (full pagination is the admin table screens' job).
  const allDepartments = useQuery({
    queryKey: ["departments", "all"],
    queryFn: fetchAllDepartments,
  });
  const wards = useQuery({ queryKey: ["wards"], queryFn: fetchWards });
  const allWards = useQuery({ queryKey: ["wards", "all"], queryFn: fetchAllWards });
  const beds = useQuery({ queryKey: ["beds"], queryFn: fetchBeds });

  const departmentForm = useForm<DepartmentValues>({
    resolver: zodResolver(departmentSchema),
    defaultValues: {
      facility: "",
      name: "",
      effective_from: today(),
      opd_enabled: false,
      ipd_enabled: false,
    },
  });
  const wardForm = useForm<WardValues>({
    resolver: zodResolver(wardSchema),
    defaultValues: { department: "", name: "", type_tag: "" },
  });
  const bedForm = useForm<BedValues>({
    resolver: zodResolver(bedSchema),
    defaultValues: { ward: "", bed_number: "" },
  });

  const addDepartment = useMutation({
    mutationFn: createDepartment,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["departments"] });
    },
  });
  const addWard = useMutation({
    mutationFn: createWard,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["wards"] });
    },
  });
  const addBed = useMutation({
    mutationFn: createBed,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["beds"] });
    },
  });

  const save = useSaveSetupStep("departments_wards_beds");
  const dirty =
    departmentForm.formState.isDirty ||
    wardForm.formState.isDirty ||
    bedForm.formState.isDirty;
  useStepDirtyBridge(dirty, onDirtyChange);

  const counts = {
    departments: departments.data?.count ?? 0,
    wards: wards.data?.count ?? 0,
    beds: beds.data?.count ?? 0,
  };
  const saveDraft = () => save.mutate({ status: "in_progress", payload: counts });
  const complete = () =>
    save.mutate({ status: "complete", payload: counts }, { onSuccess: onAdvance });

  const departmentNames = new Map((allDepartments.data ?? []).map((row) => [row.id, row.name]));
  const wardNames = new Map((allWards.data ?? []).map((row) => [row.id, row.name]));
  const noFacility =
    facilities.isSuccess && (facilities.data?.results.length ?? 0) === 0;

  const departmentNameExists = (candidate: string) =>
    (allDepartments.data ?? []).some(
      (row) => row.name.trim().toLowerCase() === candidate.trim().toLowerCase(),
    );
  // Bed codes are numbered per ward; the check sees only the loaded page
  // (the beds table stays single-page) — advisory, like the name check.
  const bedCodeExists = (ward: string, candidate: string) =>
    (beds.data?.results ?? []).some(
      (row) =>
        row.ward === ward &&
        row.bed_number.trim().toLowerCase() === candidate.trim().toLowerCase(),
    );

  return (
    <div>
      <ResourceSection
        title="Departments"
        loading={departments.isPending}
        rows={departments.data?.results ?? []}
        rowKey={(row) => row.id}
        emptyText="No departments yet."
        totalCount={departments.data?.count ?? null}
        columns={[
          { key: "name", header: "Name", render: (row) => row.name },
          { key: "opd", header: "OPD", render: (row) => (row.opd_enabled ? "Yes" : "No") },
          { key: "ipd", header: "IPD", render: (row) => (row.ipd_enabled ? "Yes" : "No") },
          {
            key: "effective_from",
            header: "Effective from",
            render: (row) => row.effective_from,
          },
        ]}
      >
        {noFacility && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            No facility exists for this tenant yet — onboarding creates the
            first facility.
          </p>
        )}
        <StepAlert error={addDepartment.error} />
        <form
          className="mt-3"
          noValidate
          onSubmit={departmentForm.handleSubmit((values) => {
            if (departmentNameExists(values.name)) {
              departmentForm.setError("name", {
                message: "A department with this name already exists.",
              });
              return;
            }
            addDepartment.mutate(values, {
              onSuccess: () =>
                departmentForm.reset({
                  facility: values.facility,
                  name: "",
                  effective_from: today(),
                  opd_enabled: false,
                  ipd_enabled: false,
                }),
              onError: (error) => {
                const { fieldErrors } = extractServerErrors(error);
                if ("name" in fieldErrors) {
                  departmentForm.setError("name", { message: fieldErrors.name });
                }
                if ("facility" in fieldErrors) {
                  departmentForm.setError("facility", { message: fieldErrors.facility });
                }
                if ("effective_from" in fieldErrors) {
                  departmentForm.setError("effective_from", {
                    message: fieldErrors.effective_from,
                  });
                }
              },
            });
          })}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="department-facility">Facility</Label>
              <select
                id="department-facility"
                className={selectClass}
                aria-invalid={departmentForm.formState.errors.facility ? true : undefined}
                aria-describedby={
                  departmentForm.formState.errors.facility
                    ? "department-facility-error"
                    : undefined
                }
                {...departmentForm.register("facility")}
              >
                <option value="">Select facility…</option>
                {(facilities.data?.results ?? []).map((facility) => (
                  <option key={facility.id} value={facility.id}>
                    {facility.name}
                  </option>
                ))}
              </select>
              {departmentForm.formState.errors.facility && (
                <p id="department-facility-error" className="text-sm text-destructive">
                  {departmentForm.formState.errors.facility.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="department-name">Department name</Label>
              <Input
                id="department-name"
                type="text"
                aria-invalid={departmentForm.formState.errors.name ? true : undefined}
                aria-describedby={
                  departmentForm.formState.errors.name ? "department-name-error" : undefined
                }
                {...departmentForm.register("name")}
              />
              {departmentForm.formState.errors.name && (
                <p id="department-name-error" className="text-sm text-destructive">
                  {departmentForm.formState.errors.name.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="department-effective-from">Effective from</Label>
              <Input
                id="department-effective-from"
                type="date"
                {...departmentForm.register("effective_from")}
              />
            </div>
            <div className="flex items-center gap-4 pt-6">
              <div className="flex items-center gap-2">
                <input
                  id="department-opd"
                  type="checkbox"
                  className="size-4 rounded border-input accent-primary"
                  {...departmentForm.register("opd_enabled")}
                />
                <Label htmlFor="department-opd">OPD enabled</Label>
              </div>
              <div className="flex items-center gap-2">
                <input
                  id="department-ipd"
                  type="checkbox"
                  className="size-4 rounded border-input accent-primary"
                  {...departmentForm.register("ipd_enabled")}
                />
                <Label htmlFor="department-ipd">IPD enabled</Label>
              </div>
            </div>
          </div>
          <Button type="submit" variant="outline" className="mt-3" disabled={addDepartment.isPending}>
            Add department
          </Button>
        </form>
      </ResourceSection>

      <ResourceSection
        title="Wards"
        loading={wards.isPending}
        rows={wards.data?.results ?? []}
        rowKey={(row) => row.id}
        emptyText="No wards yet."
        totalCount={wards.data?.count ?? null}
        columns={[
          { key: "name", header: "Name", render: (row) => row.name },
          { key: "type_tag", header: "Type", render: (row) => row.type_tag },
          {
            key: "department",
            header: "Department",
            render: (row) => departmentNames.get(row.department) ?? row.department,
          },
        ]}
      >
        <StepAlert error={addWard.error} />
        <form
          className="mt-3"
          noValidate
          onSubmit={wardForm.handleSubmit((values) =>
            addWard.mutate(values, {
              onSuccess: () =>
                wardForm.reset({ department: "", name: "", type_tag: "" }),
              onError: (error) => {
                const { fieldErrors } = extractServerErrors(error);
                if ("name" in fieldErrors) {
                  wardForm.setError("name", { message: fieldErrors.name });
                }
                if ("department" in fieldErrors) {
                  wardForm.setError("department", { message: fieldErrors.department });
                }
                if ("type_tag" in fieldErrors) {
                  wardForm.setError("type_tag", { message: fieldErrors.type_tag });
                }
              },
            }),
          )}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor="ward-department">Department</Label>
              <select
                id="ward-department"
                className={selectClass}
                aria-invalid={wardForm.formState.errors.department ? true : undefined}
                aria-describedby={
                  wardForm.formState.errors.department ? "ward-department-error" : undefined
                }
                {...wardForm.register("department")}
              >
                <option value="">Select department…</option>
                {(allDepartments.data ?? []).map((department) => (
                  <option key={department.id} value={department.id}>
                    {department.name}
                  </option>
                ))}
              </select>
              {wardForm.formState.errors.department && (
                <p id="ward-department-error" className="text-sm text-destructive">
                  {wardForm.formState.errors.department.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="ward-name">Ward name</Label>
              <Input
                id="ward-name"
                type="text"
                aria-invalid={wardForm.formState.errors.name ? true : undefined}
                {...wardForm.register("name")}
              />
              {wardForm.formState.errors.name && (
                <p className="text-sm text-destructive">
                  {wardForm.formState.errors.name.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="ward-type">Ward type</Label>
              <select
                id="ward-type"
                className={selectClass}
                aria-invalid={wardForm.formState.errors.type_tag ? true : undefined}
                {...wardForm.register("type_tag")}
              >
                <option value="">Select type…</option>
                {WARD_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
              {wardForm.formState.errors.type_tag && (
                <p className="text-sm text-destructive">
                  {wardForm.formState.errors.type_tag.message}
                </p>
              )}
            </div>
          </div>
          <Button type="submit" variant="outline" className="mt-3" disabled={addWard.isPending}>
            Add ward
          </Button>
        </form>
      </ResourceSection>

      <ResourceSection
        title="Beds"
        loading={beds.isPending}
        rows={beds.data?.results ?? []}
        rowKey={(row) => row.id}
        emptyText="No beds yet."
        totalCount={beds.data?.count ?? null}
        columns={[
          { key: "bed_number", header: "Bed number", render: (row) => row.bed_number },
          {
            key: "ward",
            header: "Ward",
            render: (row) => wardNames.get(row.ward) ?? row.ward,
          },
          {
            key: "functional",
            header: "Functional",
            render: (row) => (row.functional ? "Yes" : "No"),
          },
        ]}
      >
        <StepAlert error={addBed.error} />
        <form
          className="mt-3"
          noValidate
          onSubmit={bedForm.handleSubmit((values) => {
            if (bedCodeExists(values.ward, values.bed_number)) {
              bedForm.setError("bed_number", {
                message: "A bed with this number already exists in this ward.",
              });
              return;
            }
            addBed.mutate(values, {
              onSuccess: () => bedForm.reset({ ward: "", bed_number: "" }),
              onError: (error) => {
                const { fieldErrors } = extractServerErrors(error);
                if ("bed_number" in fieldErrors) {
                  bedForm.setError("bed_number", { message: fieldErrors.bed_number });
                }
                if ("ward" in fieldErrors) {
                  bedForm.setError("ward", { message: fieldErrors.ward });
                }
              },
            });
          })}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="bed-ward">Ward</Label>
              <select
                id="bed-ward"
                className={selectClass}
                aria-invalid={bedForm.formState.errors.ward ? true : undefined}
                aria-describedby={bedForm.formState.errors.ward ? "bed-ward-error" : undefined}
                {...bedForm.register("ward")}
              >
                <option value="">Select ward…</option>
                {(allWards.data ?? []).map((ward) => (
                  <option key={ward.id} value={ward.id}>
                    {ward.name}
                  </option>
                ))}
              </select>
              {bedForm.formState.errors.ward && (
                <p id="bed-ward-error" className="text-sm text-destructive">
                  {bedForm.formState.errors.ward.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="bed-number">Bed number</Label>
              <Input
                id="bed-number"
                type="text"
                aria-invalid={bedForm.formState.errors.bed_number ? true : undefined}
                aria-describedby={
                  bedForm.formState.errors.bed_number ? "bed-number-error" : undefined
                }
                {...bedForm.register("bed_number")}
              />
              {bedForm.formState.errors.bed_number && (
                <p id="bed-number-error" className="text-sm text-destructive">
                  {bedForm.formState.errors.bed_number.message}
                </p>
              )}
            </div>
          </div>
          <Button type="submit" variant="outline" className="mt-3" disabled={addBed.isPending}>
            Add bed
          </Button>
        </form>
      </ResourceSection>

      <StepFooter
        onBack={onBack}
        dirty={dirty}
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
