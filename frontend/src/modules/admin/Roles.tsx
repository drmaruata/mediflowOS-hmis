/**
 * Roles — tenant RBAC administration at /admin/roles (TEN-004; UI_UX §7
 * "Roles administration").
 *
 * The matrix presents the backend-enforced vocabulary (BACKEND_PERMISSION_CODES
 * in admin.api.ts — every string RequirePermission / WritePermissionMixin
 * matches, grep'd from the identity viewsets) plus whatever custom codes the
 * role already carries, visible and editable, because the `permissions`
 * claim is a free-text list server-side. The backend stays the authority:
 * the screen's write affordances render only for a session holding
 * identity.roles.write, RoleSerializer refuses platform.* codes on tenant
 * roles (so those toggles render disabled, not live-then-400), and saving
 * invalidates ["roles", tenantId] — the claim bundle a token will actually
 * carry is never left stale on screen.
 */

import { Link } from "react-router-dom";
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
import {
  BACKEND_PERMISSION_CODES,
  formAlertText,
  isPlatformCode,
  updateRole,
  fetchRoles,
} from "./admin.api";
import type { Role, RolePatch } from "./admin.api";

const WRITE_CLAIM = "identity.roles.write";

const matrixSchema = z.object({
  // RHF checkbox group: every register("permissions") checkbox with a
  // `value` contributes its checked codes to this array.
  permissions: z.array(z.string()),
  require_mfa: z.boolean(),
  allows_break_glass: z.boolean(),
});

type MatrixValues = z.infer<typeof matrixSchema>;

export default function Roles() {
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;
  const canWrite = session.data?.permissions.includes(WRITE_CLAIM) ?? false;
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const roles = useQuery({
    queryKey: ["roles", tenantId],
    queryFn: fetchRoles,
    enabled: tenantId !== null,
  });
  const selected = (roles.data ?? []).find((role) => role.id === selectedId) ?? null;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-bold tracking-tight text-card-foreground">Roles</h2>
        <Button asChild variant="outline">
          <Link to="/admin/users">Users</Link>
        </Button>
      </div>

      <ResourceSection
        title="Role catalogue"
        loading={roles.isPending}
        rows={roles.data ?? []}
        rowKey={(row) => row.id}
        emptyText="No roles yet."
        columns={[
          { key: "name", header: "Name", render: (row) => row.name },
          {
            key: "permissions",
            header: "Permissions",
            render: (row) => String(row.permissions.length),
          },
          {
            key: "mfa",
            header: "MFA",
            render: (row) => (row.require_mfa ? "Yes" : "No"),
          },
          {
            key: "break-glass",
            header: "Break-glass",
            render: (row) => (row.allows_break_glass ? "Yes" : "No"),
          },
          {
            key: "action",
            header: "Action",
            render: (row) => (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setSelectedId(row.id)}
              >
                {canWrite ? "Edit" : "View"}
              </Button>
            ),
          },
        ]}
      />

      {selected !== null && (
        <RoleMatrix key={selected.id} role={selected} canWrite={canWrite} tenantId={tenantId} />
      )}
    </div>
  );
}

interface RoleMatrixProps {
  role: Role;
  canWrite: boolean;
  tenantId: string | null;
}

/** The selected role's editable permission set. Remounts per role via key. */
function RoleMatrix({ role, canWrite, tenantId }: RoleMatrixProps) {
  const queryClient = useQueryClient();
  const form = useForm<MatrixValues>({
    resolver: zodResolver(matrixSchema),
    defaultValues: {
      permissions: role.permissions,
      require_mfa: role.require_mfa,
      allows_break_glass: role.allows_break_glass,
    },
  });
  // Codes the role carries beyond the backend vocabulary stay visible and
  // editable (the claim is free text server-side); added codes join them.
  const [extraCodes, setExtraCodes] = useState<string[]>(() =>
    role.permissions.filter(
      (code) => !(BACKEND_PERMISSION_CODES as readonly string[]).includes(code),
    ),
  );
  const [customCode, setCustomCode] = useState("");
  const [customError, setCustomError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (patch: RolePatch) => updateRole(role.id, patch),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["roles", tenantId] });
    },
  });

  const codes = [...BACKEND_PERMISSION_CODES, ...extraCodes];

  const addCustom = () => {
    const code = customCode.trim();
    if (code === "") {
      setCustomError("Enter a permission code.");
      return;
    }
    const current = form.getValues("permissions");
    if (codes.includes(code) || current.includes(code)) {
      setCustomError("This code is already in the matrix.");
      return;
    }
    setExtraCodes((prev) => [...prev, code]);
    form.setValue("permissions", [...current, code], { shouldDirty: true });
    setCustomCode("");
    setCustomError(null);
  };

  return (
    <section aria-label="Permission matrix" className="mt-6">
      <h2 className="text-base font-semibold text-card-foreground">
        Permission matrix — {role.name}
      </h2>
      <form
        className="mt-2"
        noValidate
        onSubmit={form.handleSubmit((values) => save.mutate(values))}
      >
        <ul className="grid gap-2 sm:grid-cols-2">
          {codes.map((code) => (
            <li key={code} className="flex items-center gap-2">
              <input
                id={`perm-${code}`}
                type="checkbox"
                className="size-4 rounded border-input accent-primary"
                value={code}
                disabled={!canWrite || isPlatformCode(code)}
                {...form.register("permissions")}
              />
              <Label htmlFor={`perm-${code}`}>{code}</Label>
              {isPlatformCode(code) && (
                <span className="text-xs text-muted-foreground">
                  (platform-scope roles only)
                </span>
              )}
            </li>
          ))}
        </ul>

        <div className="mt-3 flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <input
              id="role-require-mfa"
              type="checkbox"
              className="size-4 rounded border-input accent-primary"
              disabled={!canWrite}
              {...form.register("require_mfa")}
            />
            <Label htmlFor="role-require-mfa">MFA required</Label>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="role-break-glass"
              type="checkbox"
              className="size-4 rounded border-input accent-primary"
              disabled={!canWrite}
              {...form.register("allows_break_glass")}
            />
            <Label htmlFor="role-break-glass">Break-glass allowed</Label>
          </div>
        </div>

        {canWrite && (
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <div className="grid gap-1.5">
              <Label htmlFor="custom-permission-code">Custom permission code</Label>
              <Input
                id="custom-permission-code"
                type="text"
                className="max-w-xs"
                value={customCode}
                onChange={(event) => setCustomCode(event.target.value)}
              />
              {customError !== null && (
                <p className="text-sm text-destructive">{customError}</p>
              )}
            </div>
            <Button type="button" variant="outline" onClick={addCustom}>
              Add code
            </Button>
          </div>
        )}

        {save.error !== null && (
          <p
            role="alert"
            className="mt-3 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {formAlertText(save.error) ?? "The role could not be saved."}
          </p>
        )}
        {save.isSuccess && !form.formState.isDirty && (
          <p role="status" className="mt-3 text-sm text-muted-foreground">
            Role saved.
          </p>
        )}

        {canWrite ? (
          <Button type="submit" className="mt-4" disabled={save.isPending}>
            Save role
          </Button>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">
            Editing requires the {WRITE_CLAIM} permission; the matrix is read-only.
          </p>
        )}
      </form>
    </section>
  );
}
