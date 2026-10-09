# R1 Foundation — Complete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take every R1 (Foundation) requirement in the SRS from its current
partial state to implemented-and-tested: tenancy/RBAC/MFA, facility setup,
patient registration, ABHA QR + ABDM exchange, audit, platform services, the
R1 frontend screens, and the quality gates that keep it from regressing.

**Architecture:** The backend stays as it is — Django 5.2 + DRF, one app per
bounded context, tenant binding via `TenantMiddleware` + `set_config` inside
`ATOMIC_REQUESTS`, schema-qualified tables, RLS migrations. Work happens in
three layers per domain: models/migrations (expand-only), a `services.py`
module holding the business rule, and the DRF view/serializer exposing it.
The frontend grows one folder per backend module under `src/modules/`, with
route-level lazy loading and TanStack Query for all server state.

**Tech Stack:** Django 5.2 LTS, DRF 3.18, SimpleJWT (token_blacklist app),
Celery 5.6 + django-celery-beat, Channels 4.3, drf-spectacular, `cryptography`
(new — see Task 12), React 18.3 + React Router 7 + TanStack Query 5 +
React Hook Form + Zod + Tailwind v4/shadcn/ui, Vitest.

**Specs (read before executing):**
- `docs/SaaS HMIS SRS v0.5.md` — the 70 R1 requirements (§3.1–3.3, §4.1–4.4, §4.14)
- `docs/SaaS HMIS Architecture v0.6.md` — §7 tenancy, §8.4 ABDM, §14 frontend
- `docs/SaaS HMIS UI_UX_design.md` — §7 (R1 screen specs), §18.2 route inventory
- `docs/traceability.md` — regenerated status matrix (regenerate after every track)
- `AGENTS.md` — binding workflow rules (Context7 first, skills, doc sync)

## Global Constraints

These apply to every task unless a task says otherwise.

- Every new tenant-owned model carries `tenant_id = models.UUIDField(db_index=True)`; composite indexes lead with `tenant_id` (`models.Index(fields=["tenant_id", ...])`).
- Every new model sets an explicit schema-qualified `db_table` (`identity.`, `registry.`, `opd.`, `abdm.`, `audit.`, `platform.`, `integration.`). Follow the owning app's existing schema prefix (e.g. abdm tables use `abdm.`; note `ABHACallbackLog` is also duplicated at `registry.abdm_callback_log` — Task 15 removes the duplicate).
- **Every new table created after the app's `0004_enable_row_level_security` migration needs its own policy DDL.** Copy the pattern from the existing `0004` migration; a table without a `tenant_isolation` policy is a cross-tenant hole in production (non-owner role, no BYPASSRLS). Prove each new table in `tests/integration/test_rls_isolation.py`.
- Migrations are expand-only. Never drop or rename a column in the release that stops writing it.
- Deny by default: `IsAuthenticated` stays the only global permission; never add `AllowAny` to a tenant-owned endpoint. The ABDM callback remains the only unauthenticated tenant-owned endpoint, throttled by `AbdmHipThrottle`.
- Serializers use explicit `fields`, never `"__all__"` (fix every existing `"__all__"` you touch — Tasks 11, 15). `id`, `created_at`, `tenant_id` and all server-owned values are read-only.
- Never log PHI. Log identifiers only.
- Python: ruff line length 100, Google-style docstrings, requirement IDs in module docstrings (`"""Patient registry services (REG-001, REG-003 ...)."""`).
- TypeScript: `strict` mode, no `any`/`@ts-ignore`, `import type` for type-only imports, 2-space indent, semicolons, double quotes.
- Backend tests: `@pytest.mark.unit` or `@pytest.mark.integration` (`--strict-markers`), live in `tests/`, run on SQLite test settings without external services. Postgres-only assertions go behind the `requires_postgres` gate.
- Frontend tests: `*.unit.test.ts(x)` / `*.integration.test.tsx`, `screen.getByRole` over test ids, `vi.stubGlobal("fetch")` + `vi.unstubAllGlobals()` in `afterEach`, wrap in `QueryClientProvider` with `defaultOptions: { queries: { retry: false } }`.
- **Any new/changed dependency is a documentation-bearing change**: update `AGENTS.md` §3, `README.md` tables, and `docs/SaaS HMIS Architecture v0.6.md` §4 in the same commit (`tests/unit/test_dependency_wiring.py` must be extended for new backend deps).
- Context7 before any unfamiliar API: verified IDs are in `AGENTS.md` §1 (`/jazzband/djangorestframework-simplejwt`, `/celery/celery` already queried for Tasks 1 and 23; query `/websites/ui_shadcn`, `/remix-run/react-router`, `/tanstack/query` before frontend tasks).
- Commit style: Conventional Commits; security/tenant-isolation changes use scope `security`.

## Review Focus

Inputs and failure modes the spec implies but no single task naturally tests.
Each line names the owning task and its pinning test.

1. **Cross-tenant leakage on every table this plan creates** (11 new models). Owner: each creating task + Task 38. Test: a row-per-new-table case in `tests/integration/test_rls_isolation.py` asserting tenant A cannot read tenant B's row through the API *and* through the raw queryset.
2. **Concurrent UHID/token-number generation** — two registrations at the same moment must not collide (`unique_together [tenant_id, uhid]` would 500). Owner: Task 10. Test: `test_uhid_unique_under_concurrent_creation` using `transaction.atomic()` + `select_for_update` on the sequence row; assert the second caller blocks and gets the next number.
3. **ABDM callback retries double-writing** (consent event + token issued twice for one `requestId`). Owner: Tasks 16/17. Test: `test_callback_retry_creates_single_consent_event_and_token` — POST the same `requestId` twice, assert one `ConsentEvent`, one `Token`, and the *original* ack body is returned.
4. **Audit hash-chain ordering under concurrent writes** — a lost `prev_hash` silently breaks tamper-evidence. Owner: Task 21. Test: `test_hash_chain_verifies_after_interleaved_writes` — write from two simulated users, run the verify endpoint, expect `{"valid": true, "checked": n}`; then mutate one row in-place and expect `valid: false` naming the row.
5. **Refresh-token rotation breaking live sessions** — `BLACKLIST_AFTER_ROTATION` without the blacklist app installed raises at runtime; rotating without carrying the tenant claims loses the tenant binding on refresh. Owner: Task 1. Test: `test_refresh_preserves_tenant_claims` — refresh returns a token that still resolves the same tenant, and the old refresh token is rejected afterwards.
6. **Crypto failing on SQLite in tests but Postgres in prod** — encryption must be backend-agnostic (pure Python, no `pgcrypto`). Owner: Task 12. Test: round-trip + determinism tests run on the default SQLite settings.

---

## Requirement coverage map

All 70 SRS R1 requirements (63 M + 7 S) → owning task. Regenerating
`docs/traceability.md` after the last task must show every R1 row at a status
better than `partial` unless the requirement is S-priority and explicitly
marked deferred in its task.

| Task | Requirement IDs |
| --- | --- |
| 1 | TEN-006, (enables UI-003/001 auth) |
| 2 | TEN-004, TEN-002 (verification), TEN-008 (roles/memberships) |
| 3 | TEN-008 (users) |
| 4 | TEN-007 |
| 5 | TEN-001, TEN-010, TEN-011 |
| 6 | SET-001, SET-008, SET-009 |
| 7 | SET-006, SET-007 |
| 8 | SET-002, SET-003, SET-004, SET-005, SET-010, SET-011, SET-012 |
| 9 | SET-013 (S) |
| 10 | REG-001, REG-010, ABD-010 |
| 11 | REG-002, REG-003, REG-005, REG-006, REG-007 |
| 12 | REG-008 |
| 13 | REG-011, REG-012 |
| 14 | REG-009 (S), REG-013 (S) |
| 15 | ABD-003, ABD-004, ABD-005, ABD-006, ABD-007 |
| 16 | ABD-011, ABD-012 |
| 17 | ABD-008, ABD-009 |
| 18 | ABD-001, ABD-002, ABD-013, ABD-014 (S) |
| 19 | ABD-017 |
| 20 | AUD-001, AUD-003 |
| 21 | AUD-002, AUD-004 |
| 22 | PLT-001, INT-012 |
| 23 | PLT-004, INT-014 |
| 24 | PLT-005 |
| 25 | PLT-006 (S) |
| 26 | PLT-003, PLT-008, INT-013 |
| 27 | INT-001, INT-011 |
| 28 | INT-002 |
| 29 | INT-009 (S) |
| 30–37 | UI-001, UI-002, UI-003, UI-006, HW-001 (+ R1 screens per UI_UX §7) |
| 38–39 | gate: NFR-SEC/NFR-PRV via G6, doc sync |

SET-002..005 already have modelled CRUD (Task 8 adds the missing behaviour
tests); ABD-003/004/006/008/010 already work (Tasks 15/10/17 add the pinning
tests their Known gaps name).

## File structure

New files this plan creates (existing files it modifies are named per task):

```text
backend/
├── apps/identity_tenancy/
│   ├── services.py              # onboard_tenant(), next setup helpers (Task 5)
│   ├── permissions.py           # RequirePermission (Task 2)
│   ├── migrations/000X_...      # SetupProgress, ReferenceData, BaselineInput,
│   │                            # ConfigRevision, Bed.active, + RLS policy DDL
│   └── setup/…                  # (serializers/views folded into existing modules)
├── apps/patient_registry/
│   ├── services.py              # generate_uhid(), find_duplicates() (Tasks 10, 11)
│   └── migrations/000X_...      # PatientSequence, *_idx hash columns + RLS
├── apps/opd/services.py         # next_token_number(), TokenSeries (Task 10)
├── apps/abdm_gateway/
│   ├── consent.py               # record_consent_event(), link-token crypto (Task 16)
│   └── migrations/000X_...      # ConsentEvent, link_token_enc + RLS
├── apps/audit/services.py       # hash chain writer/verifier (Task 21)
├── apps/platform/migrations/000X_...  # FeatureFlag re-added (Task 25) + RLS
├── common/crypto.py             # encrypt/decrypt/HMAC index (Task 12)
├── config/settings/base.py      # MFA permission, beat schedule (Tasks 1, 23)
└── config/urls.py               # refresh/blacklist routes live in app urls

frontend/src/
├── modules/setup/               # setup wizard screens (Task 32)
├── modules/patient_registry/    # registration, list, detail, duplicates, queue (Task 33)
├── modules/admin/               # users, roles, departments, audit (Task 34)
├── modules/kiosk/               # counter display (Task 35)
├── modules/print/               # OP slip templates (Task 36)
├── modules/notifications/       # bell + inbox (Task 37)
└── lib/apiClient.ts             # refresh interceptor (Task 30)

tests/
├── unit/test_traceability_freshness.py   # (Task 38)
└── integration/test_rls_isolation.py     # extended in every model task
```

---

## Track 0 — Auth and authorization foundations

### Task 1: Token refresh, blacklist, and enforced MFA (TEN-006)

**Files:**
- Modify: `backend/apps/identity_tenancy/urls.py`
- Modify: `backend/apps/identity_tenancy/tokens.py` (`TenantAwareTokenSerializer`)
- Modify: `backend/config/settings/base.py` (INSTALLED_APPS, DEFAULT_PERMISSION_CLASSES)
- Modify: `backend/common/mfa.py` (docstring truthfulness)
- Test: `tests/integration/test_authentication.py` (extend), `tests/unit/test_project_settings.py` (extend)

**Interfaces:**
- Consumes: SimpleJWT `TokenRefreshView`, `TokenBlacklistView`, blacklist app (Context7-verified: app must be in `INSTALLED_APPS` for `BLACKLIST_AFTER_ROTATION` to work).
- Produces: routes `POST /api/v1/auth/token/refresh/`, `POST /api/v1/auth/token/blacklist/`; token claims `requires_mfa: bool`, `mfa_verified: bool` on every access token; `MFARequiredIfConfigured` active as a default permission.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.integration
def test_refresh_preserves_tenant_claims(client, active_user_with_tokens):
    """Refresh must re-bind tenant/facility/role claims — a bare refresh that
    drops them would silently un-scope every follow-up request (TEN-006)."""
    # POST /api/v1/auth/token/refresh/ with the refresh token
    # assert 200, and decoding the new access token yields the same
    # tenant_id/facility_id/permissions as the original.

@pytest.mark.integration
def test_old_refresh_token_rejected_after_rotation(client, ...):
    # reuse the pre-refresh token → 401 (blacklist app actually installed)

@pytest.mark.integration
def test_mfa_claim_blocks_unverified_session(...):
    # token with requires_mfa=True, mfa_verified=False → any authenticated
    # endpoint returns 403 with code "mfa_required"

@pytest.mark.unit
def test_mfa_permission_is_installed(settings):
    assert "common.mfa.MFARequiredIfConfigured" in \
        settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]
```

- [ ] **Step 2: Run and confirm failure** — `python -m pytest tests/integration/test_authentication.py tests/unit/test_project_settings.py -q` → FAIL (404 on refresh, missing claim, missing permission).

- [ ] **Step 3: Implement** — add `rest_framework_simplejwt.token_blacklist` to `INSTALLED_APPS` and run `python manage.py migrate` (its migrations are expand-only); add the two routes in `identity_tenancy/urls.py` using `TokenRefreshView`/`TokenBlacklistView` (no `AllowAny` change needed — these views are token-authenticated by design, keep `authentication_classes=[]` consistent with the token obtain view); in `TenantAwareTokenSerializer.get_token`, write `requires_mfa` (from `membership.role.require_mfa`) and `mfa_verified` (from `django_otp` state, default `False`) into the claims; append `MFARequiredIfConfigured` to `DEFAULT_PERMISSION_CLASSES` after `IsAuthenticated`; fix `common/mfa.py` docstring to describe what it actually does.

- [ ] **Step 4: Run and confirm passing** — same pytest command → PASS.

- [ ] **Step 5: Commit** — `feat(security): enforce MFA claim and add token refresh/blacklist routes (TEN-006)`

### Task 2: RBAC enforcement + tenant scoping of roles/memberships (TEN-004, TEN-002)

**Files:**
- Create: `backend/apps/identity_tenancy/permissions.py`
- Modify: `backend/apps/identity_tenancy/views.py:16-77` (TenantViewSet, RoleViewSet, UserMembershipViewSet)
- Modify: `backend/apps/quality_os/views.py`, `backend/apps/platform/views.py:51` (unscoped `ScheduledJobViewSet`)
- Test: `tests/integration/test_rbac_enforcement.py` (new), `tests/integration/test_tenant_scoping.py` (extend)

**Interfaces:**
- Produces: `class RequirePermission(BasePermission): def __init__(self, permission: str)` — reads the `permissions` claim from `request.auth.payload`; viewsets declare `permission_classes = [IsAuthenticated, RequirePermission("identity.roles.write")]` for writes; `TenantViewSet` requires `platform.tenants.manage` for every method.

- [ ] **Step 1: Write failing tests** — `test_role_list_is_tenant_scoped` (tenant A's role names never appear in tenant B's `GET /roles/`), `test_membership_write_denied_without_permission` (token whose `permissions` claim lacks the code → 403), `test_tenant_crud_denied_for_tenant_admin` (non-platform token → 403 on `GET/POST /tenants/`), `test_scheduled_job_list_is_tenant_scoped`.
- [ ] **Step 2: Run → confirm FAIL** (roles leak today, writes succeed today).
- [ ] **Step 3: Implement** `RequirePermission` (deny when the claim is absent — fail closed; platform scope = `Role.tenant is None`), add `TenantScopedQuerysetMixin` to `RoleViewSet`/`UserMembershipViewSet`/`ScheduledJobViewSet`, move `UserMembershipViewSet.perform_create` auditing onto the mixin hooks, gate `TenantViewSet` on the platform permission, add `permission_classes` to the four global `quality_os` viewsets (read: any authenticated tenant user; write: `quality.catalogue.manage`).
- [ ] **Step 4: Run → PASS**, plus `python -m pytest -m integration -q` full pass (no regression).
- [ ] **Step 5: Commit** — `feat(security): enforce permission claims and tenant-scope role/membership/job querysets (TEN-004)`

### Task 3: User management endpoints (TEN-008)

**Files:**
- Create: `backend/apps/identity_tenancy/serializers.py` additions (`UserSerializer`, `UserCreateSerializer`)
- Modify: `views.py`, `urls.py` (router `users`)
- Test: `tests/integration/test_user_management.py`

**Interfaces:**
- Produces: `GET/POST /api/v1/users/`, `GET/PATCH /api/v1/users/{id}/`, `POST /api/v1/users/{id}/deactivate/`. Create accepts `{username, password, email, role_id, facility_id}` and creates `auth.User` + `UserMembership(active=True)` in one transaction. Never returns or accepts a password hash. Deactivate sets `UserMembership.active=False` (no deletes — audit history must survive).

- [ ] **Step 1: failing tests** — create user with role → 201 + membership exists; password never in response body; cross-tenant `GET /users/{id}/` → 404; deactivate → subsequent login with that user rejected (extend `TenantAwareTokenSerializer.validate` to refuse inactive memberships); create without `identity.users.manage` → 403.
- [ ] **Step 2: run → FAIL** (404, no route).
- [ ] **Step 3: implement** (mixin on the viewset; `perform_create` writes audit via mixin; `UserCreateSerializer.validate_password` minimal policy: ≥12 chars).
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(identity): user management endpoints (TEN-008)`

### Task 4: Break-glass alert, audit record, revocation (TEN-007)

**Files:**
- Modify: `backend/apps/identity_tenancy/auth_views.py:114-159` (BreakGlassView), `views.py:80` (register `BreakGlassViewSet`), `urls.py`
- Test: `tests/integration/test_authentication.py` (extend)

**Interfaces:**
- Produces: `GET /api/v1/break-glass/{id}/revoke/` (platform/tenant-admin only). `BreakGlassView.post` additionally writes `AuditEvent(action="break-glass", reason=<header>, entity_type/resource id)` and a `Notification(type="critical", title="Break-glass access granted")` for every active tenant membership with `role.require_mfa` (the alert required by TEN-007).

- [ ] **Step 1: failing tests** — `test_break_grant_writes_audit_and_alert` (assert AuditEvent + Notification rows exist with the reason), `test_break_grant_without_reason_still_400`, `test_break_revoke_sets_revoked_at` and a revoked id no longer satisfies `BREAK_GLASS_CLAIM` checks.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (persist-before-notify: create the `Notification(persisted=True, delivered=False)` row first — Task 22's consumer flips `delivered`).
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(security): break-glass alerting, audit record and revocation (TEN-007)`

### Task 5: Tenant onboarding with seed configuration (TEN-001, TEN-010, TEN-011)

**Files:**
- Create: `backend/apps/identity_tenancy/services.py`
- Modify: `views.py:21-27` (`TenantViewSet.onboard`)
- Create: `docs/tenant-onboarding.md` (the "repeatable, documented process" TEN-010 demands)
- Test: `tests/integration/test_tenant_onboarding.py`

**Interfaces:**
- Produces: `def onboard_tenant(*, name: str, slug: str, facility: dict, admin: dict, abdm: dict | None = None) -> Tenant` — one transaction creating Tenant, first Facility (with `abdm_hip_id`/`abdm_facility_id`/`abdm_registration_status` → TEN-011), default Departments (OPD/IPD enabled), a `platform_admin` and a `tenant_admin` Role with seed permissions, and the first admin user+membership (reuse Task 3's serializers). Exposed as the existing `POST /tenants/onboard/`.

- [ ] **Step 1: failing tests** — onboard returns 201 and every artifact exists; a second call with the same slug → 409; rollback test: force `admin` invalid → **no** Tenant row remains; onboard requires `platform.tenants.manage`; facility ABDM identifiers round-trip via `GET /facilities/{id}/`.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** `onboard_tenant` + wire the action + write `docs/tenant-onboarding.md` (API steps, seed role table, verification checklist).
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(identity): transactional tenant onboarding with seed config (TEN-010, TEN-011)`

---

## Track 1 — Facility setup and configuration (SET)

### Task 6: Resumable setup wizard state (SET-001, SET-008, SET-009)

**Files:**
- Modify: `backend/apps/identity_tenancy/models.py` (add `SetupProgress`)
- Modify: `serializers.py`, `views.py`, `urls.py`
- Create: migration `000X_setupprogress` **with RLS policy DDL** (Global Constraints)
- Test: `tests/integration/test_setup_wizard.py`

**Interfaces:**
- Model: `SetupProgress(tenant_id, step_key Char(64), status Char(16) = pending|in_progress|complete, payload JSON, updated_at)`, unique `(tenant_id, step_key)`, `db_table = "identity.setup_progress"`.
- Produces: `GET /api/v1/setup/` → ordered steps with `complete` flags; `PUT /api/v1/setup/{step_key}/` → upsert payload; `GET /api/v1/setup/?incomplete=true` → flags incomplete steps (SET-008). Steps are declared as a module-level ordered list matching UI_UX §7's wizard: `hospital_identity, ownership_level, address, abdm_hfr_ids, accreditation, departments_wards_beds, service_units, staff_positions, reference_data, indicators_baseline`.

- [ ] **Step 1: failing tests** — put step 2 → GET shows step 2 complete and steps 3+ incomplete; re-PUT step 2 → 200 update not duplicate row; step_key unknown → 404; tenant B sees none of tenant A's progress; unauthenticated → 401.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** model + viewset (mixin; writes audited by mixin → SET-012) + migration with RLS policy.
- [ ] **Step 4: run → PASS** + add a `SetupProgress` case to `test_rls_isolation.py`.
- [ ] **Step 5: commit** `feat(identity): resumable setup wizard state (SET-001, SET-008, SET-009)`

### Task 7: Reference data and indicator baseline inputs (SET-006, SET-007)

**Files:**
- Modify: `models.py` (add `ReferenceData`, `BaselineInput`), migration + RLS
- Modify: `views.py`, `urls.py`
- Test: `tests/integration/test_setup_wizard.py` (extend)

**Interfaces:**
- Models: `ReferenceData(tenant_id, kind Char(32) in {catchment_population, ambulance, essential_commodity}, key Char(128), value JSON, active Bool)` unique `(tenant_id, kind, key)`, `db_table = "identity.reference_data"`; `BaselineInput(tenant_id, indicator_source_code Char(64), period Char(16), value Float, source Char(16) = manual|imported)`, `db_table = "identity.baseline_input"`.
- Produces: `GET/POST /api/v1/reference-data/?kind=`, `DELETE /api/v1/reference-data/{id}/` (deactivate, not delete — SET-011), `GET/POST /api/v1/baseline-inputs/`.

- [ ] **Step 1: failing tests** — catchment population saved and returned for the wizard; duplicate `(kind, key)` POST → 409; deactivate keeps the row but excludes it from default list; baseline input validation rejects negative values; tenant isolation on both.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (validation lives in the serializer per AGENTS §4).
- [ ] **Step 4: run → PASS** + RLS isolation rows.
- [ ] **Step 5: commit** `feat(identity): reference data and indicator baseline inputs (SET-006, SET-007)`

### Task 8: Effective-dated config, deactivation, and audit proof (SET-002…005, SET-010, SET-011, SET-012)

**Files:**
- Modify: `models.py` (add `ConfigRevision`, add `Bed.active`)
- Modify: `views.py` (config viewsets: block hard DELETE, apply effective dating)
- Create: migration + RLS
- Test: `tests/integration/test_config_versioning.py`

**Interfaces:**
- Model: `ConfigRevision(tenant_id, entity Char(32), entity_id UUID, snapshot JSON, effective_from Date, effective_to Date null, created_by UUID)`, `db_table = "identity.config_revision"`.
- Produces: `def record_revision(instance, user) -> None` called from `perform_update` of the config viewsets (Department, Ward, Bed, ServiceUnit, StaffPosition): copies the *current* row into `ConfigRevision` with `effective_from=today`, closes the previous revision (`effective_to=yesterday`) — locked indicator periods therefore keep the historical settings (SET-010). Config viewsets return `405` on `DELETE`; deactivation is `PATCH {active: false}` (SET-011). `GET /api/v1/config-revisions/?entity=&entity_id=` exposes history.

- [ ] **Step 1: failing tests** — update a department → prior revision closed, new open, history endpoint shows both; `DELETE /departments/{id}/` → 405 and the row still exists with `active=false` after PATCH; beds expose `active` (additive migration); every config create/update writes an `AuditEvent` (SET-012) — assert row count increases for each of SET-002..005 operations; tenant isolation.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (additive `Bed.active` default `True`; expand-only).
- [ ] **Step 4: run → PASS** + RLS row for `config_revision`.
- [ ] **Step 5: commit** `feat(identity): effective-dated configuration revisions, soft-delete config (SET-010..012)`

### Task 9: CSV import/export for beds and staff positions (SET-013, S)

**Files:**
- Create: `backend/apps/identity_tenancy/csv_io.py`
- Modify: `views.py` (`@action` on `BedViewSet`, `StaffPositionViewSet`), `urls.py`
- Test: `tests/integration/test_csv_import_export.py`

**Interfaces:**
- Produces: `GET /api/v1/beds/export/` → `text/csv` attachment (columns: ward, bed_number, functional, active); `POST /api/v1/beds/import/` multipart → `{"created": n, "updated": m, "errors": [{"row": i, "reason": ...}]}`; same pair for `staff-positions`. Python stdlib `csv` only. Import is **row-validated before any write** (all-or-nothing per request, inside the atomic block).

- [ ] **Step 1: failing tests** — export returns the tenant's beds only; import round-trips an export; a row with unknown ward → 200 with that row in `errors` and **zero** rows written; malformed CSV → 422; cross-tenant ward name in import → error not silent cross-write.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** with `csv.DictReader`/`DictWriter`, serializer-driven row validation.
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(identity): CSV import/export for beds and staff positions (SET-013)`

---

## Track 2 — Patient registration and registry (REG)

### Task 10: Server-generated UHID + configurable token series (REG-001, REG-010, ABD-010)

**Files:**
- Create: `backend/apps/patient_registry/services.py`, `backend/apps/opd/services.py`
- Modify: `patient_registry/models.py` (add `PatientSequence`), `serializers.py` (uhid read-only), `views.py` (`perform_create`)
- Modify: `opd/models.py` (add `TokenSeries`), `abdm_gateway/views.py:190` (`_issue_token` reuses the shared service)
- Create: migrations + RLS for both models
- Test: `tests/integration/test_uhid_generation.py`, extend `test_phase1_foundation.py`

**Interfaces:**
- Models: `PatientSequence(tenant_id, kind Char(16) = "uhid", period Char(16) = "2026-10", next_value BigInt)` unique `(tenant_id, kind, period)`, `db_table = "registry.sequence"`; `TokenSeries(tenant_id, facility_id, department_id null, prefix Char(16), next_number Integer)`, unique `(tenant_id, facility_id, department_id)`, `db_table = "opd.token_series"`.
- Produces:
  - `def generate_uhid(*, tenant_id: UUID) -> str` → `UHID-<YYYY><MM>-<000001>`; locks the sequence row with `select_for_update` inside the request transaction (AGENTS §4: the binding is only valid inside the transaction, so this call must stay in the view path, never in a Celery task without its own tenant block).
  - `def next_token_number(*, tenant_id, facility_id, department_id) -> tuple[str, int]` → series code + number, same locking discipline; defaults series prefix to `f"{department.code or 'GEN'}"`.
  - `PatientSerializer`: explicit `fields`, `uhid`/`verification_status`/`created_at` read-only; `PatientViewSet.perform_create` assigns `uhid`.
  - Registration response includes `token: {series, number}` when the intake creates an OPD visit; ABDM `_issue_token` calls `next_token_number` instead of its inline logic.

- [ ] **Step 1: failing tests** — `test_uhid_generated_server_side` (POST without `uhid` → 201 with `uhid`; client-supplied `uhid` ignored); `test_uhid_unique_under_concurrent_creation` (Review Focus #2); `test_uhid_period_rolls_over_monthly`; `test_token_number_increments_per_series`; `test_abdm_token_uses_shared_series_service` (callback issues `series` from `TokenSeries`, not `QR-<uuid>`); tenant isolation on both tables + RLS rows.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** services + models + migrations (RLS) + serializer/view changes.
- [ ] **Step 4: run → PASS** (both new test files + full suite).
- [ ] **Step 5: commit** `feat(registry): server-generated UHID and configurable OPD token series (REG-001, REG-010)`

### Task 11: Duplicate warning, intake channel, hardened patient serializer (REG-002, 003, 005, 006, 007)

**Files:**
- Modify: `patient_registry/services.py`, `serializers.py`, `views.py`
- Test: `tests/integration/test_patient_registration.py` (new)

**Interfaces:**
- Produces:
  - `def find_duplicates(*, tenant_id, candidate: dict, limit: int = 5) -> list[Patient]` — matches on exact ABHA number, else `(normalised name + DOB/year-of-birth)` or mobile; returns ranked candidates.
  - `POST /api/v1/patients/duplicate-check/` `{name, dob, mobile, abha_number}` → `{candidates: [...], warn: bool}` (REG-003, pre-save warning).
  - `PatientSerializer` becomes explicit with field-level validation (REG-007): `demographics` requires `name`, `gender`, `dob` or `age_years`; `contact.mobile` matches Indian mobile pattern; `consent_flags` keys validated against the documented set.
  - `intake_channel Char(16) in {counter, abha_qr, appointment}` — add the column (expand) and validate against `IntakePoint.type` (REG-005).
  - `search` gains `?year_of_birth=` / `?age=` approximate matching (REG-002) alongside existing UHID/name/mobile/ABHA.

- [ ] **Step 1: failing tests** — duplicate-check returns an exact-ABHA match as first candidate; create with `intake_channel="counter"` persists it; create with invalid mobile → 400 with field error; create missing `gender` → 400; `uhid`/`verification_status` in payload → ignored (read-only); `?age=45` finds a patient aged 44–46; tenant B's duplicate-check never sees tenant A's patients.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (validation in the serializer per AGENTS §4; `find_duplicates` normalises via `str.casefold()` + whitespace collapse).
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(registry): duplicate warning, intake channel, explicit patient validation (REG-003, REG-005, REG-007)`

### Task 12: Application-level field encryption (REG-008)

**Files:**
- Create: `backend/common/crypto.py`
- Modify: `backend/requirements.txt` + `backend/pyproject.toml` (**synchronized, same commit**) + `tests/unit/test_dependency_wiring.py` UNIMPLEMENTED map removal/entry
- Modify: `patient_registry/models.py` (hash index columns), `services.py`
- Modify: `backend/config/settings/base.py` (`PATIENT_FIELDS_KEY` env, no default in production)
- Create: migration (expand: add columns; contract later)
- Test: `tests/unit/test_crypto.py`, `tests/integration/test_patient_encryption.py`
- Doc: `AGENTS.md` §3 + `README.md` dependency table + Architecture §4 in the same commit (Global Constraints)

**Interfaces:**
- New dependency: `cryptography` (AES-GCM — stdlib has no authenticated encryption; Context7/`cryptography` docs must be consulted in-task before coding).
- Produces:
  - `def encrypt(plaintext: str, *, key: bytes) -> str` (base64 `v1:<iv>:<ciphertext>`), `def decrypt(token: str, *, key: bytes) -> str`, `def search_index(plaintext: str, *, key: bytes) -> str` (HMAC-SHA256, deterministic) — all pure Python, backend-agnostic (Review Focus #6).
  - Patient sensitive fields (`abha_number`, `abha_address`, `contact.mobile`) stored encrypted in place + `abha_number_idx`, `mobile_idx` HMAC columns (indexed) so REG-002 exact search still works without decryption.
  - Model properties `patient.abha_number` decrypt transparently; the queryset helper `filter_by_mobile(tenant_id, mobile)` uses the index column.

- [ ] **Step 1: failing tests** — round-trip encrypt/decrypt; same plaintext → same index, different plaintext → different index; `Patient` created with a mobile stores a non-plaintext value in the DB column and returns the plaintext through the property; `search` by mobile finds the patient via the index; missing `PATIENT_FIELDS_KEY` in a non-DEBUG setting → settings test fails loudly.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (key derivation: `PATIENT_FIELDS_KEY` env → `hashlib.pbkdf2_hmac` for the HMAC key and AES key; never log key material).
- [ ] **Step 4: run → PASS** + dependency-wiring test updated + docs updated.
- [ ] **Step 5: commit** `feat(registry): encrypt sensitive patient identifiers at rest (REG-008)` — security-scoped.

### Task 13: OP slip payload and department picker (REG-011, REG-012)

**Files:**
- Modify: `patient_registry/views.py`, `serializers.py`
- Test: `tests/integration/test_op_slip.py`

**Interfaces:**
- Produces: `GET /api/v1/visits/{visit_id}/op-slip/` → `{uhid, patient_name, token: {series, number}, department, facility, issued_at, visit_date}` (JSON print contract; rendering is Task 36). `GET /api/v1/departments/?opd_enabled=true` returns OPD-selectable departments (field already on the model — the filter is the deliverable).

- [ ] **Step 1: failing tests** — slip payload contains token + UHID + visit; another tenant's visit → 404; `?opd_enabled=true` excludes non-OPD departments; missing visit → 404.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (route under patient_registry but keyed by the OPD encounter id; use `@extend_schema` for schema accuracy).
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(registry): OP slip payload and OPD department picker (REG-011, REG-012)`

### Task 14: ABHA create/verify adapter and department QR codes (REG-009, REG-013 — S)

**Files:**
- Modify: `backend/apps/abdm_gateway/` (new `client.py`)
- Modify: `patient_registry/views.py` (QR actions)
- Test: `tests/integration/test_abha_services.py`

**Interfaces:**
- Produces: `class ABDMClient:` with `create_abha(payload)`, `verify_abha(abha, otp)` — driven by `IntegrationAdapter(config)` rows, base URL from env (`ABDM_SANDBX_BASE_URL`), `httpx` (declared-unused dependency — wiring it moves it out of the unused list; update `test_dependency_wiring.py` + docs). Sandbox-only: settings gate refuses non-sandbox URLs. `POST /api/v1/patients/{id}/abha/create/` and `.../verify/` return `503` with a structured body when sandbox credentials are absent (explicit failure, never silent success). QR encode data gains `department` code so a department-specific QR resolves the intended department (REG-013).

- [ ] **Step 1: failing tests** — missing credentials → 503 structured error; client builds the documented sandbox URL (mock httpx); department QR regenerates `encode_data` containing the department code and the regeneration is audited.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (S-priority: if the sandbox spec is unavailable, ship the adapter + 503 and record `REG-009 deferred: sandbox spec` in `docs/traceability.md` Known gaps via the generator's KNOWN_GAPS — do not fake a 200).
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(abdm): ABHA create/verify adapter and department QR codes (REG-009, REG-013)`

---

## Track 3 — ABDM exchange (ABD)

### Task 15: Real gateway authentication and strict validation (ABD-005, plus pinning tests for ABD-003/004/006/007)

**Files:**
- Modify: `backend/apps/abdm_gateway/views.py:74-91` (`_authenticate_call`)
- Modify: `backend/apps/patient_registry/models.py` (remove dead duplicate `ABHACallbackLog` at `registry.abdm_callback_log` — expand/contract: stop referencing first, drop the table in a later migration within this release only after confirming no writer; grep first)
- Modify: `backend/config/settings/base.py` (`ABDM_CLIENT_SECRET`, `ABDM_MAX_SKEW_SECONDS`)
- Test: `tests/integration/test_abdm_callback.py` (extend)

**Interfaces:**
- Produces: `_authenticate_call(request) -> bool` verifies `X-ABDM-Signature` as `HMAC-SHA256(raw_body, ABDM_CLIENT_SECRET)` compared with `hmac.compare_digest`; when `ABDM_CLIENT_SECRET` is unset the endpoint **fails closed in production settings and fails open with a warning log in DEBUG** (sandbox has no shared secret yet — this asymmetry must be asserted by a settings test). ABD-007 gains payload schema validation (required `requestId`, `timestamp`, `profile` keys → 400 well-formed error ack, not a 500).

- [ ] **Step 1: failing tests** — valid HMAC passes; tampered body fails → 401; missing signature → 401; `ABDM_CLIENT_SECRET` unset + `DEBUG=False` → 401; idempotent replay returns the *original* ack and creates no second patient/token (pin ABD-006, Review Focus #3); unknown `HIP id` → 404 (pin ABD-004); stale timestamp → 400 (pin ABD-007); cross-tenant department → 404.
- [ ] **Step 2: run → FAIL** (tampered body currently succeeds).
- [ ] **Step 3: implement** `_authenticate_call` + payload validation + remove the duplicate model if grep shows no writers.
- [ ] **Step 4: run → PASS** (all 9 existing `test_abdm_callback.py` cases still green).
- [ ] **Step 5: commit** `fix(security): verify ABDM gateway signatures (ABD-005)`

### Task 16: Persist consent events and store link tokens encrypted (ABD-011, ABD-012)

**Files:**
- Create: `backend/apps/abdm_gateway/consent.py`
- Modify: `abdm_gateway/models.py` (add `ConsentEvent`, add `link_token_enc` to `ABHACallbackLog`), migration + RLS policy (`abdm.` schema)
- Modify: `views.py:300-320`
- Test: `tests/integration/test_abdm_callback.py` (extend)

**Interfaces:**
- Model: `ConsentEvent(tenant_id, patient_id UUID, request_id, source_app, purpose, facility_id, granted_at, raw_profile_hash)` — **no raw profile/PHI in this table** (data minimisation, Architecture §8.4), `db_table = "abdm.consent_event"`.
- Produces: `def record_consent_event(*, tenant_id, patient_id, request_id, source_app, purpose, facility_id) -> ConsentEvent` and `def store_link_token(*, log_id, token) -> None` using `common.crypto.encrypt` (Task 12) into `link_token_enc`. The ack body stops returning the plaintext link token (it is stored for care-context linking, not echoed).

- [ ] **Step 1: failing tests** — one successful callback creates exactly one `ConsentEvent` with timestamp/source/purpose/facility; replay of the same `requestId` creates none (idempotent); DB contents of `consent_event` contain no patient name/ABHA (assert on dumped row); `link_token_enc` in the DB is not the plaintext token; tenant isolation + RLS row.
- [ ] **Step 2: run → FAIL** (Review Focus #3 territory).
- [ ] **Step 3: implement** inside the existing `transaction.atomic()` block so consent and patient creation commit together.
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(security): persist ABDM consent events, encrypt link tokens (ABD-011, ABD-012)`

### Task 17: Multi-candidate matching → verification queue (ABD-008, ABD-009)

**Files:**
- Modify: `abdm_gateway/views.py:100-189`
- Test: `tests/integration/test_abdm_callback.py` (extend)

**Interfaces:**
- Produces: `_match_patient` returns a discriminated result `("matched", patient) | ("candidates", list) | ("none", None)`; the callback handler:
  - exact ABHA match → link (ABD-008);
  - one strong demographic match → link + `verification_status="pending"` if confidence is demographic-only;
  - **multiple candidates → create no patient; write a verification-queue entry** (`Patient` with `verification_status="ambiguous"` + `match_candidates` recorded on the callback log, surfaced by the existing `GET /patients/verification_queue/`), ack still 200 with `token: null`;
  - none → provisional patient (current behaviour).
  ABD-008/009 already partially work — these tests pin the branch table.

- [ ] **Step 1: failing tests** — the four-branch matrix above, each asserting patient row count afterwards; ambiguous branch adds exactly one queue entry; queue visible from tenant A's `verification_queue` and invisible from tenant B.
- [ ] **Step 2: run → FAIL** (multiple-candidate branch currently collapses into provisional create).
- [ ] **Step 3: implement** branch logic in a `services.py`-style function `resolve_profile(...) -> Resolution`.
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(abdm): verification-queue branch for ambiguous profile matches (ABD-009)`

### Task 18: QR lifecycle and callback alerting (ABD-001, ABD-002, ABD-013, ABD-014 — S)

**Files:**
- Modify: `patient_registry/views.py` (`QRCodeViewSet` add `revoke`)
- Modify: `abdm_gateway/views.py` + `apps/workers/tasks.py` (alert scan task — Task 23 wires the schedule)
- Test: `tests/integration/test_qr_lifecycle.py`, `test_abdm_callback.py`

**Interfaces:**
- Produces: `POST /api/v1/qr-codes/{id}/revoke/` → sets `revoked_at`, flips `active=False`, writes audit; a revoked QR's regenerate → 409. `task_scan_callback_failures(tenant_id)` counts `ABHACallbackLog.status` failures in the last hour; over threshold → `Notification(type="critical")` (ABD-014). ABD-013 test: with `ABDM_SANDBX_BASE_URL` unreachable, counter registration (`POST /patients/`) still succeeds — pins "counter channel fully usable if gateway unavailable".

- [ ] **Step 1: failing tests** — revoke 201 + audit row + subsequent POST on revoked QR → 409; scan task creates one notification for a failure burst (idempotent: a second run in the same window doesn't duplicate); counter registration unaffected by gateway outage; `GET /qr-codes/` lists only own-tenant codes.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (revoke uses the mixin's `perform_update` audit path; alert task takes explicit `tenant_id` per AGENTS §4).
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(abdm): QR revocation and callback failure alerting (ABD-002, ABD-014)`

### Task 19: ABDM sandbox test case (ABD-017)

**Files:**
- Create: `tests/integration/test_abdm_sandbox.py`
- Doc: `docs/abdm-sandbox-runbook.md`

**Interfaces:**
- Consumes: Task 15's HMAC, Task 16's consent store, `ABDMClient` (Task 14).

- [ ] **Step 1: write the gated test** — `@pytest.mark.integration` + `@pytest.mark.skipif(not os.getenv("ABDM_SANDBX_RUN"), ...)` replaying the profile-share test case per API version through the live sandbox; asserts ack shape, consent row, token issuance.
- [ ] **Step 2: run locally without env → SKIPPED, with env → PASS** (record the run result in the runbook; ABD-017 cannot be claimed green until a real sandbox run is recorded — state this in the runbook, do not mark it done on skips alone).
- [ ] **Step 3: write `docs/abdm-sandbox-runbook.md`** (credentials env vars, exact command, expected ack, failure triage).
- [ ] **Step 4: commit** `test(abdm): sandbox profile-share test case and runbook (ABD-017)`

---

## Track 4 — Audit (AUD)

### Task 20: Working drill-down and patient read logging (AUD-001, AUD-003)

**Files:**
- Modify: `backend/apps/audit/views.py` (replace the `list` override with a `get_queryset` override)
- Modify: `backend/apps/patient_registry/views.py` (record `action="read"`)
- Test: `tests/integration/test_audit_trail.py` (new)

**Interfaces:**
- Produces: `AuditViewSet.get_queryset()` applies `entity_type`/`entity_id` filters from query params (the current `list()` implementation discards its own filtered queryset — fix by filtering where `super().list` will actually use it). `PatientViewSet.retrieve` and `search` call `audit_read(patient, request)` writing `AuditEvent(action="read", entity_type="registry.patient")` — AUD-001's read half, currently missing.

- [ ] **Step 1: failing tests** — seed 3 events across 2 resources; `GET /audit-log/?entity_type=X&entity_id=Y` returns 1 (today returns 3 — the bug is invisible only when a single event exists, so seed multiple); patient detail GET writes a `read` event with `user_id` and `source_ip`; cross-tenant event → invisible; unauthenticated → 401.
- [ ] **Step 2: run → FAIL** (drill-down returns unfiltered rows).
- [ ] **Step 3: implement** (read logging must not break search latency: write asynchronously? No — keep it synchronous inside the request transaction; volume is bounded by read rate, note perf follow-up in docstring).
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `fix(audit): repair drill-down filter and log patient reads (AUD-001, AUD-003)`

### Task 21: Tamper-evident hash chain and retention (AUD-002, AUD-004)

**Files:**
- Create: `backend/apps/audit/services.py`
- Modify: `backend/common/tenant.py` (`_write_audit_log` → chain writer)
- Modify: `backend/apps/audit/views.py` (`@action verify`)
- Modify: `backend/config/settings/base.py` (`AUDIT_RETENTION_DAYS`, beat entry from Task 23)
- Test: `tests/unit/test_audit_chain.py`, `tests/integration/test_audit_trail.py` (extend)

**Interfaces:**
- Produces:
  - `def append_event(*, tenant_id, **fields) -> AuditEvent` — computes `hash_chain = HMAC(key, prev_hash + canonical(fields))` where `prev_hash` is the tenant's last event fetched with `select_for_update` (per-tenant chain, ordered); `_write_audit_log` delegates to it.
  - `GET /api/v1/audit-log/verify/` → `{"valid": bool, "checked": int, "first_bad": id|null}` (recomputes the chain).
  - `def purge_expired(*, tenant_id, retention_days) -> int` deletes events older than `AUDIT_RETENTION_DAYS` (Task 23 schedules it); retention config lives in settings with a documented default.

- [ ] **Step 1: failing tests** — Review Focus #4 (interleaved writes verify; in-place mutation detected and reported); `purge_expired` deletes only rows older than the threshold and only for the given tenant; existing empty `hash_chain` rows are tolerated by verify (reported as `legacy` not as tampering).
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (canonical fields = sorted JSON of the same dict written to the row; key from `AUDIT_HMAC_KEY` env, checked by settings test when `DEBUG=False`).
- [ ] **Step 4: run → PASS** + full suite.
- [ ] **Step 5: commit** `feat(security): tamper-evident audit hash chain and retention purge (AUD-002, AUD-004)`

---

## Track 5 — Platform and realtime (PLT / INT)

### Task 22: Working WebSocket auth and consumer tenancy (PLT-001, INT-012)

**Files:**
- Create: `backend/apps/realtime/middleware.py` (JWT-on-query-string auth)
- Modify: `backend/config/asgi.py`, `apps/realtime/consumers.py:7,24`
- Test: `tests/integration/test_realtime_consumers.py` (new, uses `channels.testing.WebsocketCommunicator`)

**Interfaces:**
- Produces: `def token_auth_middleware(scope, receive, send)` reading `?token=<access JWT>`, validating with SimpleJWT, rejecting anonymous/foreign-tenant connections with code 4401; consumers read `scope["tenant_id"]` set by the middleware (today they read `scope["user"].tenant_id`, which never exists on `auth.User`, so **every connection is closed** — the bug this task exists to fix). `NotificationConsumer` flips `Notification.delivered=True` on push. Routes stay exactly `ws/notifications/` and `ws/vitals/` (INT-012 restriction — Task 26 pins it).

- [ ] **Step 1: failing tests** — connect with valid token → accepted; no token → close 4401; token for tenant A on a tenant B resource → never receives B's rows; notification POST creates a `persisted` row and the consumer marks `delivered`; without the fix all connects are rejected (pin the current bug as a regression test).
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** middleware + consumer change + asgi wiring (keep `AuthMiddlewareStack` for session-based consumers? No — replace with the token middleware for both routes; document why in `asgi.py`).
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `fix(realtime): JWT WebSocket auth and tenant resolution (PLT-001, INT-012)`

### Task 23: Real Celery tasks and beat schedule (PLT-004, INT-014)

**Files:**
- Modify: `backend/apps/workers/tasks.py` (replace three `pass` bodies), `backend/workers/celery.py` (remove duplicated placeholder definitions — one canonical registration)
- Modify: `backend/config/settings/base.py` (`CELERY_BEAT_SCHEDULE` via `django_celery_beat` crontab entries)
- Modify: `backend/config/settings/dev.py` keeps `CELERY_TASK_ALWAYS_EAGER=True`
- Test: `tests/unit/test_celery_tasks.py`, `tests/integration/test_scheduled_jobs.py`

**Interfaces:**
- Context7-verified: `config_from_object('django.conf:settings', namespace='CELERY')`, beat entries as `{"<name>": {"task": ..., "schedule": crontab(...)}}`.
- Produces (every task takes explicit `tenant_id`, opens `transaction.atomic()` + `set_tenant_context` inside it, `autoretry_for=(Exception,)`, `max_retries=5`, exponential backoff, and an idempotency guard so a retry cannot double-write):
  - `dispatch_notification(notification_id)` — pushes via `Notification.delivered` flip + consumer broadcast hook.
  - `purge_expired_audit_events(tenant_id)` — Task 21's `purge_expired`, scheduled nightly (`crontab(hour=2, minute=0)`).
  - `run_scheduled_job(job_id)` — picks up `platform.scheduled_job` rows, marks running/completed/failed, re-entrantly safe on `status` transition (`UPDATE ... WHERE status='pending'` pattern).
  - `scan_abdm_callback_failures(tenant_id)` — Task 18's alert, hourly.
  - Deleting the duplicate task bodies in `workers/celery.py` so a task name cannot resolve to two implementations.

- [ ] **Step 1: failing tests** — each task with eager execution reaches its end state; retry idempotency: invoking `purge_expired_audit_events` twice deletes the same set and creates no side effects; `run_scheduled_job` run twice executes once (status guard); beat schedule contains the four entries; no `pass`-bodied task remains (assert via source inspection).
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** per interfaces; keep `CELERY_TASK_ALWAYS_EAGET=True` in dev/test.
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(workers): implement Celery tasks with beat schedule (PLT-004, INT-014)`

### Task 24: File upload with access control (PLT-005)

**Files:**
- Modify: `backend/apps/platform/views.py` (`PlatformFileViewSet` add upload/download actions), `serializers.py`
- Create: `MEDIA_ROOT` storage handling in settings
- Test: `tests/integration/test_platform_files.py`

**Interfaces:**
- Produces: `POST /api/v1/files/` multipart upload → stores under `MEDIA_ROOT/<tenant_id>/<uuid>/<filename>`, row in `platform.file` with `uploaded_by`; `GET /api/v1/files/{id}/download/` → streams the file **only** to the owning tenant (404 cross-tenant), `Content-Disposition` attachment; file types limited to an allow-list (pdf, png, jpg, csv, json); size cap from settings (`MAX_UPLOAD_MB`, default 10).

- [ ] **Step 1: failing tests** — upload 201 + file exists under tenant dir; cross-tenant download → 404; `.exe` upload → 400; unauthenticated download → 401; oversize → 400; RLS row for `platform.file` (note: this table post-dates the app's `0004` migration and currently has **no policy** — this task adds it).
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (serve via the API view, never via `django.views.static.serve` in production).
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(platform): tenant-isolated file upload and download (PLT-005)`

### Task 25: Feature flags (PLT-006 — S)

**Files:**
- Modify: `backend/apps/platform/models.py` (re-add `FeatureFlag`), migration + RLS
- Modify: `views.py`, `urls.py`
- Test: `tests/integration/test_feature_flags.py`

**Interfaces:**
- Model: `FeatureFlag(tenant_id, key Char(64), enabled Bool default False, description Char(255))` unique `(tenant_id, key)`, `db_table = "platform.feature_flag"` — re-added after `0005` deleted it (expand migration; `0004` still lists the old table on Postgres — the new migration must be a plain `CreateModel`, not a re-run of `0001`).
- Produces: `GET /api/v1/feature-flags/`, `PUT /api/v1/feature-flags/{key}/`, `def flag_enabled(tenant_id, key) -> bool` helper for backend checks.

- [ ] **Step 1: failing tests** — default off; toggle then `flag_enabled` True; unknown key → False (fail closed); tenant isolation + RLS row; platform-admin-only write.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement**.
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(platform): per-tenant feature flags (PLT-006)`

### Task 26: Pin the polling/Channels split (PLT-003, PLT-008, INT-013)

**Files:**
- Test: `tests/integration/test_transport_split.py` (new)
- Modify (only if a pin fails): `config/asgi.py`, board endpoints

**Interfaces:**
- Consumes: existing `tokens/queue`, `bed-status/board`, `triages/tracking-board` endpoints and `apps/realtime/routing.py`.

- [ ] **Step 1: write the pins** — `test_operational_boards_are_rest_not_websocket` (the three board endpoints return 200 JSON without any WS involvement); `test_websocket_routes_are_only_notifications_and_vitals` (walk `get_resolver`/`websocket_urlpatterns` and assert the route set is exactly `ws/notifications/`, `ws/vitals/` — INT-012/PLT-008); `test_board_endpoints_are_tenant_scoped` (tenant B sees no rows of tenant A for queue/board/tracking-board); `test_emergency_tracking_board_filters` — **also covers the latent `FieldError`**: `?status=` on the emergency board currently 500s because `Triage` has no `status` field; fix the filter (use the model's real severity/triage field) in this task.
- [ ] **Step 2: run → FAIL** (emergency filter test fails with `FieldError`).
- [ ] **Step 3: fix** the emergency filter and any pin that reveals an unrouted board.
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `fix(tests): pin REST-vs-Channels transport split; repair emergency board filter (PLT-003, INT-013)`

---

## Track 6 — Integration (INT)

### Task 27: OpenAPI schema gate (INT-001, INT-011)

**Files:**
- Create: `tests/integration/test_openapi_schema.py`
- Modify: CI config (add schema step to the existing backend workflow)

**Interfaces:**
- Consumes: `python manage.py spectacular --file schema.yml` (AGENTS §8).

- [ ] **Step 1: failing test** — run `spectacular --file` in-process and assert: exit success, schema parses as YAML, contains `paths` for `/api/v1/auth/token/`, `/api/v1/patients/`, `/api/v1/abdm-callbacks/`, and `components.securitySchemes` exists; assert **zero** `drf_spectacular` warnings on stderr (INT-001's "publish an OpenAPI specification" is only met when the schema generates cleanly).
- [ ] **Step 2: run → FAIL** (warnings exist today — e.g. missing `@extend_schema` on custom actions).
- [ ] **Step 3: fix** the warnings (annotate actions with `@extend_schema`, add serializer references) rather than suppressing them.
- [ ] **Step 4: run → PASS** + add the same command to CI.
- [ ] **Step 5: commit** `feat(api): clean OpenAPI schema generation gate (INT-001, INT-011)`

### Task 28: Versioned ABDM adapter (INT-002)

**Files:**
- Modify: `backend/apps/abdm_gateway/client.py` (from Task 14)
- Modify: `backend/apps/integration/models.py` (add `api_version Char(16)` to `IntegrationAdapter`, expand migration)
- Test: `tests/integration/test_abha_services.py` (extend)

**Interfaces:**
- Produces: `class ABDMClient.for_adapter(adapter: IntegrationAdapter)` — dispatches to `V2ProfileShare` or `V3ProfileShare` payload builders keyed by `adapter.api_version` (`"v2"|"v3"`); the callback's ack builder takes the same version so the response shape matches the requesting API version. Adapter rows: `IntegrationAdapter(name="abdm", adapter_type="rest", api_version="v2")`.

- [ ] **Step 1: failing tests** — v2 request → v2 ack shape; v3 → v3; unsupported version → 422 with a clear message; both versions idempotently replay (Task 15's test parametrised over versions).
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** builders as pure functions (payload → payload) so they are unit-testable without network.
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(abdm): versioned profile-share adapter (INT-002)`

### Task 29: OIDC single sign-on exchange (INT-009 — S)

**Files:**
- Create: `backend/apps/identity_tenancy/oidc.py`
- Modify: `urls.py` (`auth/oidc/`), `settings/base.py` (`OIDC_*` env config)
- Test: `tests/integration/test_oidc_login.py`

**Interfaces:**
- New dependency: none beyond what exists — `httpx` (declared, unused → wiring it is a doc-sync + `test_dependency_wiring.py` update) and PyJWT's `PyJWKClient` for ID-token verification.
- Produces: `POST /api/v1/auth/oidc/` `{id_token}` → validates issuer/audience/signature via the IdP JWKS, maps `email`/`sub` to a local `auth.User` (SCIM-less just-in-time provisioning gated by `OIDC_JIT_PROVISION` flag), binds the tenant from a configured claim mapping, returns the same token pair as `auth/token/`. Settings: `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URI` — absent config → 501 with structured body (explicit not-implemented, mirroring the ABDM honesty pattern), never a fake 200.

- [ ] **Step 1: failing tests** — valid signed token (generate a test RSA key locally, publish JWKS from a stub) → 200 token pair; wrong audience → 401; expired → 401; unconfigured settings → 501; JIT-disabled + unknown user → 403; tenant binding applied to the issued token claims.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (S-priority: if the tenant IdP metadata is unavailable, ship the 501-configured path and record the deferral in KNOWN_GAPS with a note — honest partial beats fake green).
- [ ] **Step 4: run → PASS** + docs: `README.md` OIDC env vars + `AGENTS.md` §3 dependency wiring note for `httpx`.
- [ ] **Step 5: commit** `feat(auth): OIDC ID-token exchange endpoint (INT-009)`

---

## Track 7 — Frontend R1 screens (UI / HW)

Global for this track: every task starts with a Context7 query for the API it
uses (`/remix-run/react-router`, `/tanstack/query`, `/websites/ui_shadcn`,
`/reactjs/react.dev/__branch__v18`). All routes are lazy-loaded, all server
state through TanStack Query with structured keys `["<module>", tenantId,
filters]`, all forms React Hook Form + Zod (established in `LoginPage.tsx`).

### Task 30: Authentication end-to-end (UI-001 foundation)

**Files:**
- Modify: `frontend/src/lib/apiClient.ts`, `src/modules/auth/auth.api.ts`, `src/stores/authStore.ts`, `src/App.tsx`, `src/components/AppHeader.tsx`
- Create: `src/modules/auth/MfaChallenge.tsx`, `src/lib/tokenRefresh.ts`
- Test: `src/lib/tokenRefresh.unit.test.ts`, `src/modules/auth/auth.integration.test.tsx`

**Interfaces:**
- Consumes: Task 1's `auth/token/refresh/`, `auth/token/blacklist/`, `auth/me/`.
- Produces: `apiClient` runs a single-flight refresh on 401 (one in-flight
  refresh shared by concurrent 401s), retries the original request once, and
  redirects to sign-in on refresh failure; `logout()` calls the blacklist
  endpoint then `clearTokens()` and is wired to the user menu (currently a
  placeholder in `AppHeader.tsx:162`); `useSession()` hook fetches
  `GET /auth/me/` (query key `["auth","me"]`) exposing role/permissions to
  the UI; MFA challenge route renders when `requires_mfa && !mfa_verified`
  (Task 1's claim, surfaced through `/auth/me/`).

- [ ] **Step 1: failing tests** — 401 then refresh then successful retry (fetch mock sequence); two concurrent 401s trigger exactly one refresh; refresh failure → tokens cleared + navigate to sign-in; logout clears sessionStorage and hits blacklist; MFA-required user with unconfirmed device sees the challenge before the dashboard.
- [ ] **Step 2: run → FAIL** (`npm run test`).
- [ ] **Step 3: implement** (single-flight via a module-level `Promise` in `tokenRefresh.ts`; cleanup in `afterEach` with `vi.unstubAllGlobals()`).
- [ ] **Step 4: run → PASS** + `npm run check`.
- [ ] **Step 5: commit** `feat(frontend): end-to-end auth — refresh, logout, MFA challenge (UI-001)`

### Task 31: Route contract and module scaffolds

**Files:**
- Modify: `src/App.tsx`, `src/lib/navigation.ts`, `src/modules/auth/LoginPage.tsx`
- Create: `src/modules/<each>/__routes.tsx` placeholders for setup, patient_registry, admin, kiosk, notifications

**Interfaces:**
- Decision: the UI_UX design is the route contract — canonical paths move to
  the spec: `/auth/sign-in` (was `/login`), `/dashboard` (was `/`). Keep
  redirects (`<Route path="/login" ...>` → Navigate) so existing links and
  tests do not break. Each new module folder exports a `lazy()`-loaded
  route element; `App.tsx` stays the route table only (AGENTS §5).

- [ ] **Step 1: failing tests** — `navigation.unit.test.ts` asserts the spec paths for the R1 screens resolve; visiting `/login` redirects to `/auth/sign-in` (AppShell integration test); `/dashboard` renders the dashboard (moved from `/`).
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** path changes + redirects + module scaffold folders with a single `Placeholder` view each (nav items flip from `disabled` to routed only as their task lands — `IMPLEMENTED_ROUTES` grows per task).
- [ ] **Step 4: run → PASS** + `npm run check`.
- [ ] **Step 5: commit** `feat(frontend): align routes with UI_UX contract, scaffold R1 modules`

### Task 32: Setup wizard screens (SET-001, SET-007, SET-008, SET-009)

**Files:**
- Create: `src/modules/setup/SetupWizard.tsx`, `steps/*.tsx`, `setup.api.ts`
- Test: `src/modules/setup/setup.integration.test.tsx`

**Interfaces:**
- Consumes: Task 6/7 endpoints (`GET /setup/`, `PUT /setup/{step}/`, reference-data, baseline-inputs).
- Produces: a 10-step resumable wizard matching UI_UX §7 `/admin/setup`; incomplete steps flagged visually; on return, `GET /setup/` restores state; step navigation is keyboard-reachable (UI-002); department/ward/bed steps reuse shared CRUD table components colocated in `modules/setup/components/`.

- [ ] **Step 1: failing tests** — wizard lists 10 steps with completion state from the API; saving step 1 PUTs and marks complete; resuming shows restored values; incomplete steps show the flag label (role-based queries); nav item `/admin/setup` enabled in `navigation.ts`.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (RHF + Zod per step schema; `useQuery(["setup"])` + `useMutation` with invalidation of `["setup"]`).
- [ ] **Step 4: run → PASS** + `npm run check`.
- [ ] **Step 5: commit** `feat(frontend): setup wizard screens (SET-001)`

### Task 33: Patient registration, search, duplicates, verification queue (REG-001…007, UI-002)

**Files:**
- Create: `src/modules/patient_registry/`: `PatientList.tsx`, `PatientRegistration.tsx`, `PatientDetail.tsx`, `DuplicateWarning.tsx`, `VerificationQueue.tsx`, `patient.api.ts`, types next to fetch functions
- Test: `patient.unit.test.ts`, `patient.integration.test.tsx`

**Interfaces:**
- Consumes: Task 10/11/13 endpoints — `POST /patients/` (server UHID), `POST /patients/duplicate-check/`, `GET /patients/?search=&age=`, `GET /patients/verification_queue/`, `GET /patients/{id}/`, `GET /departments/?opd_enabled=true`.
- Produces: registration form (RHF+Zod) that runs `duplicate-check` on name+DOB/mobile blur and shows `DuplicateWarning` with "register anyway" requiring a confirm; on submit the response UHID/token render in a success panel linking to OP-slip print (Task 36); `PatientDetail` shows demographics with an unsynced/verification badge; `VerificationQueue` lists `verification_status=pending|ambiguous` with a verify action hitting `POST /patients/{id}/verify/`. Keyboard-first: Enter submits each section, focus moves to the next field (UI-002).

- [ ] **Step 1: failing tests** — registration creates a patient and displays the server UHID (never client-entered); duplicate warning appears when the API returns candidates and "register anyway" is required; verification queue lists pending patients and verify removes one; role="button" landmarks present (getByRole); cross-tenant data cannot render (query is tenant-scoped by base client — asserted via mock).
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement**.
- [ ] **Step 4: run → PASS** + `npm run check`.
- [ ] **Step 5: commit** `feat(frontend): patient registration, duplicate warning, verification queue (REG-001..006)`

### Task 34: Admin screens — users, roles, departments, wards/beds, audit, break-glass (TEN-004, TEN-007, TEN-008, AUD-003)

**Files:**
- Create: `src/modules/admin/`: `Users.tsx`, `Roles.tsx` (permission matrix from the `permissions` claim vocabulary), `DepartmentsWardsBeds.tsx`, `AuditLog.tsx` (drill-down table + `?entity_type=&entity_id=` filtering), `BreakGlassDialog.tsx`, `admin.api.ts`
- Test: `admin.integration.test.tsx`

**Interfaces:**
- Consumes: Task 2/3/4/20 endpoints.
- Produces: permission-gated screens (hidden when the session's `permissions` claim lacks the code — UI-side enforcement is cosmetic; the backend is authoritative per Task 2); `AuditLog` supports clicking a patient row → drill-down filtered view (AUD-003); `BreakGlassDialog` requires a reason textarea and sends the `X-Break-Glass-Reason` header, then shows the granted `access_id` + expiry.

- [ ] **Step 1: failing tests** — users list renders from API; role save invalidates `["roles", tenantId]`; audit drill-down issues the filtered request and shows only matching rows; break-glass submit disabled until reason non-empty; screens hidden without permission claim.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement**.
- [ ] **Step 4: run → PASS** + `npm run check`.
- [ ] **Step 5: commit** `feat(frontend): admin, audit drill-down and break-glass screens (TEN-004/007/008, AUD-003)`

### Task 35: Kiosk counter display (UI-003)

**Files:**
- Create: `src/modules/kiosk/TokenDisplay.tsx`, `kiosk.api.ts`
- Test: `src/modules/kiosk/TokenDisplay.integration.test.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/opd/tokens/queue/?department_id=` via REST polling (Architecture §14: **polling, not Channels**).
- Produces: `/kiosk/tokens/:displayId` route — no interactive login (reuses a read-only token issued to the display; simplest R1: kiosk auth = a facility-scoped read token from `auth/token` with a `kiosk` role that Task 2's permission model allows read-only queue access); auto-reconnect = `refetchInterval: 5_000` + visible offline banner when two consecutive polls fail; large-font current/next token layout, `aria-live="polite"` for screen readers.

- [ ] **Step 1: failing tests** — renders tokens from mocked polling; after two failed fetches the offline banner appears; interval registered and cleaned up on unmount (StrictMode-safe — assert `clearInterval` via fake timers); route added to nav as enabled.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement**.
- [ ] **Step 4: run → PASS** + `npm run check`.
- [ ] **Step 5: commit** `feat(frontend): kiosk counter display with REST polling (UI-003)`

### Task 36: OP slip and receipt print templates (UI-006, HW-001)

**Files:**
- Create: `src/modules/print/OpSlip.tsx`, `src/styles/print.css`
- Modify: `src/modules/patient_registry/PatientRegistration.tsx` (print link)
- Test: `src/modules/print/OpSlip.integration.test.tsx`

**Interfaces:**
- Consumes: Task 13's `GET /visits/{id}/op-slip/`.
- Produces: `/print/op-slip/:visitId` — a print-optimised view (no app chrome, `@media print` rules, hospital name/address/logo slot from facility data, QR of the UHID via the existing `QRCode` payload), `window.print()` button; works at 80mm thermal width and A4 (HW-001: standard receipt and A4 printers). Receipt printing for billing stays R2.

- [ ] **Step 1: failing tests** — slip renders UHID, token, department, date from the API; print button calls `window.print` (spy); print CSS applied (assert `data-print` root class); missing visit → user-visible error state, not a blank page.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** (no PDF dependency — browser print pipeline satisfies HW-001; revisit `reportlab` only if server-side PDF becomes a requirement).
- [ ] **Step 4: run → PASS** + `npm run check`.
- [ ] **Step 5: commit** `feat(frontend): OP slip print templates (UI-006, HW-001)`

### Task 37: Notifications inbox (PLT-001 UI half)

**Files:**
- Create: `src/modules/notifications/Inbox.tsx`, `notifications.api.ts`; modify `src/components/AppHeader.tsx` (bell + unread count)
- Test: `notifications.integration.test.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/notifications/`, `/notifications/unread/`, `POST /notifications/{id}/mark_read/`.
- Produces: bell with unread badge polling `unread/` every 30 s (`staleTime` aligned with the health-query reasoning in AGENTS §5); `/notifications` inbox with type-severity styling (critical/alert/info), mark-read invalidating `["notifications", tenantId, "unread"]`; the WebSocket from Task 22 upgrades the badge live when connected, with polling as the fallback (never both hammering).

- [ ] **Step 1: failing tests** — badge shows the unread count; marking read updates badge after invalidation; WS message increments the badge without a refetch; critical notifications render with the alert style.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement**.
- [ ] **Step 4: run → PASS** + `npm run check`.
- [ ] **Step 5: commit** `feat(frontend): notification bell and inbox (PLT-001)`

---

## Track 8 — Quality gates and documentation

### Task 38: CI gates — Postgres isolation, schema, traceability freshness

**Files:**
- Create: `tests/unit/test_traceability_freshness.py`
- Modify: `backend/scripts/generate_traceability.py` (extract `render() -> str` from `main()` so the test can compare without writing)
- Modify: CI workflow (postgres service + `MEDIFLOW_TEST_PG*` env for the isolation gate; `spectacular --file` step)
- Modify: `tests/unit/test_dependency_wiring.py` as tasks flip deps to wired (`httpx`)

**Interfaces:**
- Produces: `render() -> str` in the generator; test asserts
  `render() == (REPO/"docs"/"traceability.md").read_text()` — **a stale
  traceability file now fails CI**, which is the structural fix for the drift
  this audit found (AGENTS §9.10).

- [ ] **Step 1: failing test** — edit any requirement-status input without regenerating → freshness test fails; regenerate → passes.
- [ ] **Step 2: implement** `render()` refactor + test + CI job running the `requires_postgres` gate with a Postgres 16 service (skip-if-no-env becomes skip-because-CI-didn't-provision → assert the gate actually ran, e.g. fail when `CI=true && not MEDIFLOW_TEST_PGHOST`).
- [ ] **Step 3: run** — `python -m pytest -q` (full, PG env set if available) + `python -m ruff check . ../tests`.
- [ ] **Step 4: commit** `ci: pin traceability freshness and run the RLS isolation gate`

### Task 39: Doc sync and final R1 verification

**Files (expected, confirm against what each task actually changed):**
- `AGENTS.md` §3 (any dependency wired/added), `README.md` tables, `docs/SaaS HMIS Architecture v0.6.md` §4/§14/§15 as touched
- `docs/traceability.md` (regenerated)
- `docs/SaaS HMIS SRS v0.5.md` — **do not edit requirement text**; status lives in traceability only

- [ ] **Step 1: regenerate** `python scripts/generate_traceability.py` — confirm every R1 row shows `implemented`-supporting evidence or an explicit KNOWN_GAPS note; add KNOWN_GAPS entries for anything deliberately deferred (S-priority only: REG-009, REG-013, ABD-014, SET-013, INT-009, PLT-006 — each must be either done or noted).
- [ ] **Step 2: run the full gate** — `python -m pytest` (all green incl. PG gate where available), `python -m ruff check . ../tests`, `python manage.py spectacular --file schema.yml` (no warnings), `npm run check`, `npm run build`.
- [ ] **Step 3: doc-sync audit** — walk AGENTS §3's "Documentation of tech & dependency changes" checklist: for every task that added `cryptography`, wired `httpx`, or changed settings, confirm AGENTS §3 + README + Architecture §4 were updated in the *same commit* (git log inspection).
- [ ] **Step 4: Definition-of-done pass** — AGENTS §9 items 1–11, each with evidence in the report.
- [ ] **Step 5: commit** `docs: R1 completion — traceability regeneration and doc sync`

---

## Out of this plan (explicitly deferred, with reasons)

These are **not R1** requirements; do not pull them in:

- `pharmacy`/`blood_bank` routers unmounted (their viewsets 404) → **R4** modules; fix there (found in the 2026-10-06 audit, recorded in traceability's Routes column).
- `ipd` `discharge/` detail-without-pk 500 → **R2** (IPD). (The emergency
  tracking-board `?status=` `FieldError` is *in* this plan — Task 26 — because
  PLT-003's "emergency boards via polling" claim cannot be pinned against an
  endpoint that 500s when filtered.)
- `REG-004` patient merge → **R2**.
- Quality OS loader/computation (406 indicators) → **R3**.
- PWA/offline, i18n, command palette → not R1 (Architecture §14 marks offline as future).
- `TEN-003` dedicated DB per tenant → **R7**; `TEN-005` ABAC → **R2**.

## Execution notes

- **Order matters within tracks, not across them.** Track 0 first (everything
  else inherits permissions/auth). Track 2's Task 12 before Track 3's Task 16
  (consent encryption reuses `common/crypto.py`). Track 7 tasks each depend on
  their backend task but otherwise run independently.
- After every task: `python -m pytest -q` + `python -m ruff check . ../tests`
  (backend) or `npm run check` (frontend), then regenerate traceability when a
  Known gap closes.
- If a step's test cannot be written without guessing an API, stop and read
  the spec section named in that task's Files list — do not invent behaviour.
