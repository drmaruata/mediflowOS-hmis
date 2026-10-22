/**
 * DepartmentsWardsBeds — the admin configuration edit surface for the
 * wizard's CRUD rows, at /admin/departments (departments) and
 * /admin/wards-beds (wards and beds) (UI_UX §7 "Departments administration"
 * and "Wards and beds administration"; SET-002/003, SET-010, SET-011).
 *
 * What the backend actually supports, mirrored exactly: the department,
 * ward and bed viewsets gate NO permission claim of their own (authenticated
 * + tenant-scoped only — EffectiveDatedConfigMixin), so this screen renders
 * its edit affordances for any authenticated user rather than inventing a
 * gate the server does not enforce. Every PATCH archives the row's
 * pre-update state into a ConfigRevision (SET-010 — effective dating is
 * server-automatic, so there is no effective-date input here) and lands an
 * audit event; DELETE answers 405 by design, so deactivation is
 * PATCH {active: false} and the row is retained (SET-011) — the Active
 * toggle is both directions because reactivation is the same PATCH.
 *
 * Adds stay in the setup wizard (SET-009 keeps it reachable after setup);
 * this screen is the edit/deactivate half, so it renders no add-forms. Bed
 * `occupied` is deliberately absent from the edit panel: occupancy is live
 * admission state, and a writable serializer field is not a licence to let
 * configuration silently clear it (design.md §7).
 */

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ResourceSection } from "@/components/ResourceSection";
import { useSession } from "@/lib/session";
import { Pager } from "./Pager";
import {
  fetchAllDepartments,
  fetchAllWards,
  fetchBedsPage,
  formAlertText,
  updateBed,
  updateDepartment,
  updateWard,
} from "./admin.api";
import type { BedPatch, BedRow, DepartmentPatch, DepartmentRow, WardPatch, WardRow } from "./admin.api";

export type ConfigSection = "departments" | "wards-beds";

const WARD_TYPES = [
  "Medical",
  "Surgical",
  "Maternity",
  "Paediatric",
  "ICU",
  "SNCU",
  "NRC",
] as const;

const selectClass =
  "flex h-10 w-full rounded-md border border-input bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-invalid:border-destructive";

export default function DepartmentsWardsBeds({ section }: { section: ConfigSection }) {
  return (
    <div>
      <h2 className="text-xl font-bold tracking-tight text-card-foreground">
        {section === "departments" ? "Departments" : "Wards & beds"}
      </h2>
      {section === "departments" ? (
        <DepartmentsSection />
      ) : (
        <>
          <WardsSection />
          <BedsSection />
        </>
      )}
    </div>
  );
}

/**
 * Invalidating the bare ["departments"]-style key rather than the
 * tenant-scoped one: prefix matching then refreshes both this screen's
 * ["departments", tenantId] query and the setup wizard's bare-keyed one,
 * so the two surfaces cannot drift apart after an edit.
 */
function useInvalidateConfigRows() {
  const queryClient = useQueryClient();
  return {
    invalidate: (resource: "departments" | "wards" | "beds") => {
      void queryClient.invalidateQueries({ queryKey: [resource] });
    },
  };
}

function DepartmentsSection() {
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;
  const departments = useQuery({
    queryKey: ["departments", tenantId],
    queryFn: fetchAllDepartments,
    enabled: tenantId !== null,
  });
  const [editing, setEditing] = useState<DepartmentRow | null>(null);

  return (
    <ResourceSection
      title="Departments"
      loading={departments.isPending}
      rows={departments.data ?? []}
      rowKey={(row) => row.id}
      emptyText="No departments yet — add them in the setup wizard."
      columns={[
        { key: "name", header: "Name", render: (row) => row.name },
        { key: "opd", header: "OPD", render: (row) => (row.opd_enabled ? "Yes" : "No") },
        { key: "ipd", header: "IPD", render: (row) => (row.ipd_enabled ? "Yes" : "No") },
        { key: "active", header: "Active", render: (row) => (row.active ? "Yes" : "No") },
        {
          key: "effective_from",
          header: "Effective from",
          render: (row) => row.effective_from,
        },
        {
          key: "action",
          header: "Action",
          render: (row) => (
            <Button type="button" variant="outline" size="sm" onClick={() => setEditing(row)}>
              Edit
            </Button>
          ),
        },
      ]}
    >
      {editing !== null && (
        <DepartmentEditPanel key={editing.id} row={editing} onClose={() => setEditing(null)} />
      )}
    </ResourceSection>
  );
}

const departmentSchema = z.object({
  name: z.string().min(2, "Department name is required."),
  opd_enabled: z.boolean(),
  ipd_enabled: z.boolean(),
  active: z.boolean(),
});

type DepartmentValues = z.infer<typeof departmentSchema>;

function DepartmentEditPanel({
  row,
  onClose,
}: {
  row: DepartmentRow;
  onClose: () => void;
}) {
  const { invalidate } = useInvalidateConfigRows();
  const form = useForm<DepartmentValues>({
    resolver: zodResolver(departmentSchema),
    defaultValues: {
      name: row.name,
      opd_enabled: row.opd_enabled,
      ipd_enabled: row.ipd_enabled,
      active: row.active,
    },
  });
  const save = useMutation({
    mutationFn: (patch: DepartmentPatch) => updateDepartment(row.id, patch),
    onSuccess: () => {
      invalidate("departments");
      onClose();
    },
  });

  return (
    <section aria-label="Edit department" className="mt-3">
      <h2 className="text-sm font-semibold text-card-foreground">Edit {row.name}</h2>
      {save.error !== null && (
        <p
          role="alert"
          className="mt-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {formAlertText(save.error) ?? "The department could not be saved."}
        </p>
      )}
      <form
        className="mt-2 grid gap-3 sm:grid-cols-2"
        noValidate
        onSubmit={form.handleSubmit((values) => save.mutate(values))}
      >
        <div className="grid gap-1.5">
          <Label htmlFor="department-edit-name">Department name</Label>
          <Input
            id="department-edit-name"
            type="text"
            aria-invalid={form.formState.errors.name ? true : undefined}
            {...form.register("name")}
          />
          {form.formState.errors.name && (
            <p className="text-sm text-destructive">{form.formState.errors.name.message}</p>
          )}
        </div>
        <div className="flex items-center gap-4 pt-6">
          <div className="flex items-center gap-2">
            <input
              id="department-edit-opd"
              type="checkbox"
              className="size-4 rounded border-input accent-primary"
              {...form.register("opd_enabled")}
            />
            <Label htmlFor="department-edit-opd">OPD enabled</Label>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="department-edit-ipd"
              type="checkbox"
              className="size-4 rounded border-input accent-primary"
              {...form.register("ipd_enabled")}
            />
            <Label htmlFor="department-edit-ipd">IPD enabled</Label>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="department-edit-active"
              type="checkbox"
              className="size-4 rounded border-input accent-primary"
              {...form.register("active")}
            />
            <Label htmlFor="department-edit-active">Active</Label>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button type="submit" disabled={save.isPending}>
            Save department
          </Button>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}

function WardsSection() {
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;
  const wards = useQuery({
    queryKey: ["wards", tenantId],
    queryFn: fetchAllWards,
    enabled: tenantId !== null,
  });
  const departments = useQuery({
    queryKey: ["departments", tenantId],
    queryFn: fetchAllDepartments,
    enabled: tenantId !== null,
  });
  const departmentNames = new Map(
    (departments.data ?? []).map((row) => [row.id, row.name]),
  );
  const [editing, setEditing] = useState<WardRow | null>(null);

  return (
    <ResourceSection
      title="Wards"
      loading={wards.isPending}
      rows={wards.data ?? []}
      rowKey={(row) => row.id}
      emptyText="No wards yet — add them in the setup wizard."
      columns={[
        { key: "name", header: "Name", render: (row) => row.name },
        { key: "type", header: "Type", render: (row) => row.type_tag },
        {
          key: "department",
          header: "Department",
          render: (row) => departmentNames.get(row.department) ?? row.department,
        },
        { key: "active", header: "Active", render: (row) => (row.active ? "Yes" : "No") },
        {
          key: "action",
          header: "Action",
          render: (row) => (
            <Button type="button" variant="outline" size="sm" onClick={() => setEditing(row)}>
              Edit
            </Button>
          ),
        },
      ]}
    >
      {editing !== null && (
        <WardEditPanel key={editing.id} row={editing} onClose={() => setEditing(null)} />
      )}
    </ResourceSection>
  );
}

const wardSchema = z.object({
  department: z.string().uuid("Select the department."),
  name: z.string().min(2, "Ward name is required."),
  type_tag: z.string().min(1, "Select the ward type."),
  active: z.boolean(),
});

type WardValues = z.infer<typeof wardSchema>;

function WardEditPanel({ row, onClose }: { row: WardRow; onClose: () => void }) {
  const { invalidate } = useInvalidateConfigRows();
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;
  const departments = useQuery({
    queryKey: ["departments", tenantId],
    queryFn: fetchAllDepartments,
    enabled: tenantId !== null,
  });
  const form = useForm<WardValues>({
    resolver: zodResolver(wardSchema),
    defaultValues: {
      department: row.department,
      name: row.name,
      type_tag: row.type_tag,
      active: row.active,
    },
  });
  const save = useMutation({
    mutationFn: (patch: WardPatch) => updateWard(row.id, patch),
    onSuccess: () => {
      invalidate("wards");
      onClose();
    },
  });

  return (
    <section aria-label="Edit ward" className="mt-3">
      <h2 className="text-sm font-semibold text-card-foreground">Edit {row.name}</h2>
      {save.error !== null && (
        <p
          role="alert"
          className="mt-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {formAlertText(save.error) ?? "The ward could not be saved."}
        </p>
      )}
      <form
        className="mt-2 grid gap-3 sm:grid-cols-2"
        noValidate
        onSubmit={form.handleSubmit((values) => save.mutate(values))}
      >
        <div className="grid gap-1.5">
          <Label htmlFor="ward-edit-name">Ward name</Label>
          <Input
            id="ward-edit-name"
            type="text"
            aria-invalid={form.formState.errors.name ? true : undefined}
            {...form.register("name")}
          />
          {form.formState.errors.name && (
            <p className="text-sm text-destructive">{form.formState.errors.name.message}</p>
          )}
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="ward-edit-type">Ward type</Label>
          <select
            id="ward-edit-type"
            className={selectClass}
            aria-invalid={form.formState.errors.type_tag ? true : undefined}
            {...form.register("type_tag")}
          >
            {WARD_TYPES.map((type) => (
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
        <div className="grid gap-1.5">
          <Label htmlFor="ward-edit-department">Department</Label>
          <select
            id="ward-edit-department"
            className={selectClass}
            aria-invalid={form.formState.errors.department ? true : undefined}
            {...form.register("department")}
          >
            {(departments.data ?? []).map((department) => (
              <option key={department.id} value={department.id}>
                {department.name}
              </option>
            ))}
          </select>
          {form.formState.errors.department && (
            <p className="text-sm text-destructive">
              {form.formState.errors.department.message}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 pt-6">
          <input
            id="ward-edit-active"
            type="checkbox"
            className="size-4 rounded border-input accent-primary"
            {...form.register("active")}
          />
          <Label htmlFor="ward-edit-active">Active</Label>
        </div>
        <div className="flex items-center gap-2">
          <Button type="submit" disabled={save.isPending}>
            Save ward
          </Button>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}

function BedsSection() {
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;
  const [page, setPage] = useState(1);
  const beds = useQuery({
    queryKey: ["beds", tenantId, page],
    queryFn: () => fetchBedsPage(page),
    enabled: tenantId !== null,
  });
  const wards = useQuery({
    queryKey: ["wards", tenantId],
    queryFn: fetchAllWards,
    enabled: tenantId !== null,
  });
  const wardNames = new Map((wards.data ?? []).map((row) => [row.id, row.name]));
  const [editing, setEditing] = useState<BedRow | null>(null);

  return (
    <ResourceSection
      title="Beds"
      loading={beds.isPending}
      rows={beds.data?.results ?? []}
      rowKey={(row) => row.id}
      emptyText="No beds yet — add them in the setup wizard."
      totalCount={beds.data?.count ?? null}
      columns={[
        { key: "bed_number", header: "Bed number", render: (row) => row.bed_number },
        { key: "ward", header: "Ward", render: (row) => wardNames.get(row.ward) ?? row.ward },
        {
          key: "functional",
          header: "Functional",
          render: (row) => (row.functional ? "Yes" : "No"),
        },
        { key: "active", header: "Active", render: (row) => (row.active ? "Yes" : "No") },
        {
          key: "action",
          header: "Action",
          render: (row) => (
            <Button type="button" variant="outline" size="sm" onClick={() => setEditing(row)}>
              Edit
            </Button>
          ),
        },
      ]}
    >
      {editing !== null && (
        <BedEditPanel key={editing.id} row={editing} onClose={() => setEditing(null)} />
      )}
      <Pager
        page={page}
        hasNext={Boolean(beds.data?.next)}
        onPrev={() => setPage((prev) => Math.max(1, prev - 1))}
        onNext={() => setPage((prev) => prev + 1)}
      />
    </ResourceSection>
  );
}

const bedSchema = z.object({
  bed_number: z.string().min(1, "Bed number is required."),
  functional: z.boolean(),
  active: z.boolean(),
});

type BedValues = z.infer<typeof bedSchema>;

function BedEditPanel({ row, onClose }: { row: BedRow; onClose: () => void }) {
  const { invalidate } = useInvalidateConfigRows();
  const form = useForm<BedValues>({
    resolver: zodResolver(bedSchema),
    defaultValues: {
      bed_number: row.bed_number,
      functional: row.functional,
      active: row.active,
    },
  });
  const save = useMutation({
    mutationFn: (patch: BedPatch) => updateBed(row.id, patch),
    onSuccess: () => {
      invalidate("beds");
      onClose();
    },
  });

  return (
    <section aria-label="Edit bed" className="mt-3">
      <h2 className="text-sm font-semibold text-card-foreground">
        Edit {row.bed_number}
      </h2>
      {save.error !== null && (
        <p
          role="alert"
          className="mt-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {formAlertText(save.error) ?? "The bed could not be saved."}
        </p>
      )}
      <form
        className="mt-2 grid gap-3 sm:grid-cols-2"
        noValidate
        onSubmit={form.handleSubmit((values) => save.mutate(values))}
      >
        <div className="grid gap-1.5">
          <Label htmlFor="bed-edit-number">Bed number</Label>
          <Input
            id="bed-edit-number"
            type="text"
            aria-invalid={form.formState.errors.bed_number ? true : undefined}
            {...form.register("bed_number")}
          />
          {form.formState.errors.bed_number && (
            <p className="text-sm text-destructive">
              {form.formState.errors.bed_number.message}
            </p>
          )}
        </div>
        <div className="flex items-center gap-4 pt-6">
          <div className="flex items-center gap-2">
            <input
              id="bed-edit-functional"
              type="checkbox"
              className="size-4 rounded border-input accent-primary"
              {...form.register("functional")}
            />
            <Label htmlFor="bed-edit-functional">Functional</Label>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="bed-edit-active"
              type="checkbox"
              className="size-4 rounded border-input accent-primary"
              {...form.register("active")}
            />
            <Label htmlFor="bed-edit-active">Active</Label>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button type="submit" disabled={save.isPending}>
            Save bed
          </Button>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}
