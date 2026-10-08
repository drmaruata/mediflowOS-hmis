# Tenant onboarding with seed configuration (TEN-010, TEN-011)

How a platform administrator boards a new hospital through the API, what the
one transaction creates, and how to verify the boarding succeeded.

## Who may onboard

Only the platform-scoped `platform.tenants.manage` claim may mint a tenancy
root (TEN-010). The claim is carried by a role with `Role.tenant is None` —
`RoleSerializer` refuses `platform.*` codes on tenant-scoped roles (TEN-004) —
and `TenantViewSet` requires it on **every** method, list included, so a
tenant administrator can neither enumerate other hospitals' tenants nor onboard
one. The gate is enforced on the token's `permissions` claim at request time
(`common.authentication.claims_from`), so a denial names the missing code in
the 403 body.

## Payload

`POST /api/v1/tenants/onboard/`

```json
{
  "name": "Example District Hospital",
  "slug": "example-dh",
  "facility": {
    "name": "Main Campus",
    "level": "District Hospital"
  },
  "admin": {
    "username": "hospital-admin",
    "password": "a-strong-secret-password",
    "email": "admin@example.org"
  },
  "abdm": {
    "abdm_hip_id": "HIP-EXAMPLE-001",
    "abdm_facility_id": "1000-example-facility",
    "abdm_registration_status": "registered"
  }
}
```

The `abdm` block is optional (TEN-011): a hospital may board before NHA
registration and backfill the identifiers through `PATCH /api/v1/facilities/{id}/`
later. When it is absent the facility's `abdm_registration_status` defaults to
`"pending"`. `admin.password` follows Task 3's rule (at least 12 characters,
enforced server-side).

| Status | Meaning |
| --- | --- |
| `201` | Tenant created; response body is the tenant (matches `GET /tenants/{id}/`). |
| `400` | Payload invalid — including a password shorter than 12 characters. Nothing was written. |
| `403` | The caller's token lacks `platform.tenants.manage`. |
| `409` | A tenant with this `slug` already exists (`slug` is globally unique). |

## What one 201 creates

Everything below is written inside a single `transaction.atomic()` in
`apps/identity_tenancy/services.py`. A failure at any point — including an
invalid admin password — rolls the whole boarding back, so a partially created
hospital can never exist. `ATOMIC_REQUESTS` is False in the test profile, which
is why the transaction lives in the service rather than the view layer.

| Artifact | Values |
| --- | --- |
| `identity.tenant` | `name`, `slug` from the payload. |
| `identity.facility` | The first facility, stamped with the `abdm_*` identifiers (TEN-011). |
| `identity.department` | `OPD` (`opd_enabled`, not `ipd_enabled`) and `IPD` (`ipd_enabled`, not `opd_enabled`), both `active`, both bound to the facility. |
| `identity.role` | `platform_admin` and `tenant_admin`, tenant-scoped, with explicit permission codes (see below). |
| `auth_user` + `identity.user_membership` | The first administrator, bound with an `active` membership to `platform_admin`. |

## Seed roles

Seeded permissions are explicit codes only — `"all"` is a human marker the
RBAC gate never reads (see `seed_dev_data.py`) — and carry no `platform.*`
code, which is illegal on tenant-scoped roles (TEN-004).

| Role | Seeds |
| --- | --- |
| `platform_admin` (tenant-scoped) | `identity.users.manage`, `identity.roles.write`, `identity.memberships.write`, `identity.break_glass.revoke`, `identity.setup.manage` |
| `tenant_admin` (tenant-scoped) | `identity.users.manage`, `identity.roles.write`, `identity.memberships.write`, `identity.setup.manage` |

Both seeds carry `identity.setup.manage` (SET-001): onboarding exits into the
setup wizard, so the seeded admins can read and write wizard state immediately
instead of waiting for someone to mint a gated role first.

The platform operator's own account and role are seeded separately by
`manage.py seed_dev_data`; onboarding only seeds **this** tenant's roles.

## Verification checklist

1. `POST /api/v1/tenants/onboard/` returns `201` and the tenant id.
2. `GET /api/v1/facilities/{id}/` as the seeded admin returns the facility
   with `abdm_hip_id`, `abdm_facility_id` and `abdm_registration_status`
   matching what was sent (TEN-011).
3. `GET /api/v1/departments/` lists exactly `OPD` and `IPD`, both active,
   with the correct service switches.
4. `POST /api/v1/auth/token/` with the seeded admin's credentials succeeds
   (the first account is actually usable), and the token's `permissions`
   claim matches the seed bundle.
5. Boarding the same `slug` a second time returns `409` and creates nothing.
6. The ABDM callback (`/api/v1/abdm/hip/callback/`) resolves the facility by
   `abdm_hip_id`.

## Implementation

- `backend/apps/identity_tenancy/services.py` — `onboard_tenant`, the single
  transaction and seed helpers.
- `backend/apps/identity_tenancy/serializers.py` — `OnboardTenantSerializer`
  and companions (`FacilitySeedSerializer`, `AbdmSeedSerializer`,
  `OnboardAdminSerializer`; the last delegates the password rule to
  `UserCreateSerializer`).
- `backend/apps/identity_tenancy/views.py` — `TenantViewSet.onboard`, which
  gates on `platform.tenants.manage`, validates, and translates the duplicate
  slug's `IntegrityError` into `409`.
- `tests/integration/test_tenant_onboarding.py` — the boundary tests for the
  above contract.