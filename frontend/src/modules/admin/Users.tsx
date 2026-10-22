/**
 * Users — tenant user administration at /admin/users (TEN-008; UI_UX §7
 * "Users administration").
 *
 * The backend contract mirrored here: reads are authorised by authentication
 * plus tenant scoping, while every write (create, deactivate) additionally
 * demands the identity.users.manage claim (UserViewSet's WritePermissionMixin)
 * — so the invite form and the deactivate action render only for a session
 * that holds it. UI-side gating is cosmetic; the server's 403 is what stops
 * a claim-less session. Deactivation is the only offboarding path: DELETE
 * does not route on UserViewSet, so no delete control exists here either —
 * the account row survives for audit history.
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
import { extractServerErrors } from "@/lib/serverErrors";
import { Pager } from "./Pager";
import {
  createUser,
  deactivateUser,
  fetchRoles,
  fetchUsersPage,
  formAlertText,
} from "./admin.api";
import type { AdminUser } from "./admin.api";

const MANAGE_CLAIM = "identity.users.manage";

const inviteSchema = z.object({
  username: z.string().min(1, "Username is required.").max(150),
  email: z.union([
    z.literal(""),
    z.string().email("Enter a valid email address."),
  ]),
  // Mirrors the server's own rule (UserCreateSerializer.validate_password)
  // so the client never posts a payload predetermined to 400.
  password: z.string().min(12, "Password must be at least 12 characters long."),
  role_id: z.string().uuid("Select a role."),
});

type InviteValues = z.infer<typeof inviteSchema>;

const selectClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 aria-invalid:border-destructive";

export default function Users() {
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;
  const canManage = session.data?.permissions.includes(MANAGE_CLAIM) ?? false;
  const queryClient = useQueryClient();
  // Page state stays local: unlike the audit screen's shareable URL filters,
  // a plain list page is not worth URL state.
  const [page, setPage] = useState(1);
  const users = useQuery({
    queryKey: ["users", tenantId, page],
    queryFn: () => fetchUsersPage(page),
    enabled: tenantId !== null,
  });
  // Shared key with the Roles screen: a role save invalidates ["roles",
  // tenantId] and this name join refreshes with it.
  const roles = useQuery({
    queryKey: ["roles", tenantId],
    queryFn: fetchRoles,
    enabled: tenantId !== null,
  });
  const roleNames = new Map((roles.data ?? []).map((role) => [role.id, role.name]));

  const inviteForm = useForm<InviteValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { username: "", email: "", password: "", role_id: "" },
  });

  const invite = useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users", tenantId] });
      inviteForm.reset({ username: "", email: "", password: "", role_id: "" });
    },
  });
  const deactivate = useMutation({
    mutationFn: deactivateUser,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users", tenantId] });
    },
  });

  const onDeactivate = (user: AdminUser) => {
    const message =
      `Deactivate ${user.username}? Their membership in this hospital is ` +
      "switched off and they cannot sign in; audit history keeps the account.";
    if (!window.confirm(message)) return;
    deactivate.mutate(user.id);
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold tracking-tight text-card-foreground">Users</h1>
        <Button asChild variant="outline">
          <Link to="/admin/roles">Roles</Link>
        </Button>
      </div>

      <ResourceSection
        title="Users"
        loading={users.isPending}
        rows={users.data?.results ?? []}
        rowKey={(row) => row.id}
        emptyText="No users yet."
        totalCount={users.data?.count ?? null}
        columns={[
          { key: "username", header: "Username", render: (row) => row.username },
          { key: "email", header: "Email", render: (row) => row.email || "—" },
          {
            key: "role",
            header: "Role",
            render: (row) =>
              (row.role_id !== null ? roleNames.get(row.role_id) : undefined) ??
              row.role_id ??
              "—",
          },
          {
            key: "status",
            header: "Status",
            render: (row) =>
              row.active === null ? "No membership" : row.active ? "Active" : "Deactivated",
          },
          {
            key: "action",
            header: "Action",
            render: (row) =>
              canManage && row.active === true ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onDeactivate(row)}
                  disabled={deactivate.isPending}
                >
                  Deactivate
                </Button>
              ) : null,
          },
        ]}
      >
        {deactivate.error !== null && (
          <p
            role="alert"
            className="mt-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {formAlertText(deactivate.error) ?? "The user could not be deactivated."}
          </p>
        )}
        <Pager
          page={page}
          hasNext={Boolean(users.data?.next)}
          onPrev={() => setPage((prev) => Math.max(1, prev - 1))}
          onNext={() => setPage((prev) => prev + 1)}
        />
      </ResourceSection>

      {canManage && (
        <section aria-label="Invite user" className="mt-6">
          <h2 className="text-base font-semibold text-card-foreground">Invite user</h2>
          {invite.error !== null && (
            <p
              role="alert"
              className="mt-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {formAlertText(invite.error) ?? "The user could not be created."}
            </p>
          )}
          {invite.isSuccess && !inviteForm.formState.isDirty && (
            <p role="status" className="mt-2 text-sm text-muted-foreground">
              User added.
            </p>
          )}
          <form
            className="mt-2 grid gap-3 sm:grid-cols-2"
            noValidate
            onSubmit={inviteForm.handleSubmit((values) =>
              invite.mutate(values, {
                onError: (error) => {
                  const { fieldErrors } = extractServerErrors(error);
                  for (const field of ["username", "email", "password", "role_id"] as const) {
                    if (field in fieldErrors) {
                      inviteForm.setError(field, { message: fieldErrors[field] });
                    }
                  }
                },
              }),
            )}
          >
            <div className="grid gap-1.5">
              <Label htmlFor="invite-username">Username</Label>
              <Input
                id="invite-username"
                type="text"
                aria-invalid={inviteForm.formState.errors.username ? true : undefined}
                aria-describedby={
                  inviteForm.formState.errors.username ? "invite-username-error" : undefined
                }
                {...inviteForm.register("username")}
              />
              {inviteForm.formState.errors.username && (
                <p id="invite-username-error" className="text-sm text-destructive">
                  {inviteForm.formState.errors.username.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="invite-email">Email</Label>
              <Input
                id="invite-email"
                type="email"
                aria-invalid={inviteForm.formState.errors.email ? true : undefined}
                aria-describedby={
                  inviteForm.formState.errors.email ? "invite-email-error" : undefined
                }
                {...inviteForm.register("email")}
              />
              {inviteForm.formState.errors.email && (
                <p id="invite-email-error" className="text-sm text-destructive">
                  {inviteForm.formState.errors.email.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="invite-password">Password</Label>
              <Input
                id="invite-password"
                type="password"
                aria-invalid={inviteForm.formState.errors.password ? true : undefined}
                aria-describedby={
                  inviteForm.formState.errors.password ? "invite-password-error" : undefined
                }
                {...inviteForm.register("password")}
              />
              {inviteForm.formState.errors.password && (
                <p id="invite-password-error" className="text-sm text-destructive">
                  {inviteForm.formState.errors.password.message}
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="invite-role">Role</Label>
              <select
                id="invite-role"
                className={selectClass}
                aria-invalid={inviteForm.formState.errors.role_id ? true : undefined}
                aria-describedby={
                  inviteForm.formState.errors.role_id ? "invite-role-error" : undefined
                }
                {...inviteForm.register("role_id")}
              >
                <option value="">Select role…</option>
                {(roles.data ?? []).map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
              </select>
              {inviteForm.formState.errors.role_id && (
                <p id="invite-role-error" className="text-sm text-destructive">
                  {inviteForm.formState.errors.role_id.message}
                </p>
              )}
            </div>
            <div>
              <Button type="submit" disabled={invite.isPending}>
                Add user
              </Button>
            </div>
          </form>
        </section>
      )}
    </div>
  );
}
