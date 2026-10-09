# AGENTS.md

Binding instructions for coding agents working in this repository. These rules
override default habits. If a rule here conflicts with a convenience, follow the
rule and say so in your final report.

---

## 1. Non-negotiable workflow

Every coding task follows this order. Skipping step 1 or 2 is a process failure
even when the code is correct.

### Step 1 — Always use Context7 before writing or changing code

Your training data is older than the installed stack. **Never** write code from
memory for any library below. Look it up first.

```
resolve-library-id  ->  query-docs
```

`query-docs` needs a *narrow, single-concept* query. Never send broad prompts
like "how do I do auth". Send one concept: "SimpleJWT token rotation and
blacklist settings", "useQuery retry and refetchInterval options".

**Verified library IDs for this stack — use these directly, skip `resolve-library-id` for these:**

| Concern | Context7 library ID |
| --- | --- |
| Django 5.2 (ORM, migrations, settings, transactions) | `/websites/djangoproject_en_5_2` |
| Django (source-level internals) | `/django/django/5_2_6` |
| Django 6.0 / 6.1 (only for upgrade planning) | `/websites/djangoproject_en_6_1` |
| Django REST Framework | `/encode/django-rest-framework` |
| DRF (website docs) | `/websites/django-rest-framework` |
| drf-spectacular | `/tfranzel/drf-spectacular` |
| React 18 | `/reactjs/react.dev/__branch__v18` |
| Shadcn UI / Tailwind | `/websites/ui_shadcn` (verified) |
| Radix UI primitives | `/websites/ui_shadcn` (composition layer) |
| Vite 6 | `/websites/v6_vite_dev` |
| React Router 7 | `/remix-run/react-router` (docs mirror: `/websites/reactrouter`) |
| TanStack Query 5 | `/tanstack/query` |
| TypeScript | `/microsoft/typescript` |
| Vitest | `/vitest-dev/vitest` |
| Celery | `/celery/celery` |
| django-celery-beat | `/celery/django-celery-beat` |
| Django Channels 4 | `/django/channels` |
| djangorestframework-simplejwt | `/jazzband/djangorestframework-simplejwt` |
| PostgreSQL (RLS, `set_config`, policies) | `/websites/postgresql_current` |
| Zod | `/colinhacks/zod` |

Anything not in this table: call `resolve-library-id` first, then `query-docs`.

**When you must look things up:** any new dependency, any API or signature you
are not certain of, any deprecation or migration path, any framework-lifecycle
or async question, any security API (JWT, CORS, CSRF, RLS, permissions).

**Version discipline:** the repo is pinned to React 18 / Shadcn UI + Tailwind
v4 / Django 5.2 LTS / Vite 6. Ant Design 5 is removed; docs for Ant Design 6
describe an API this repo no longer uses. If the pinned version and the latest docs
disagree, the pinned version wins — read the versioned ID above, and if the
feature genuinely requires the newer major, stop and report instead of
migrating silently.

### Step 2 — Always use Skills

Load a skill before implementing. Check both locations.

1. **Project workspace skills** — `.opencode/skills/` in this repo. None exist
   yet. If you add one, it takes precedence over a global skill of the same
   purpose.
2. **Global skills** — `C:\Users\USER\.config\opencode\skills` and 'C:\Users\USER\.agents\skills'.
  Load by ID via the `skill` tool.

**Mandatory skill mapping for this stack:**

| Task | Load these skills |
| --- | --- |
| Any Django backend work | `django-expert` |
| Any Python code (typing, async, structure) | `python-pro` |
| Any React component / hook | `react-expert` |
| React performance, render behaviour, memoization | `vercel-react-best-practices` |
| Any TypeScript typing question | `typescript-pro` |
| Any shadcn/ui component, Tailwind token, or theming question | `shadcn`, `shadcn-ui`, `tailwind-4-docs` |
| Any REST endpoint, versioning, or pagination design | `api-designer` |
| Auth, permissions, tenant isolation, PHI, input validation | `secure-code-guardian` |
| Any change touching auth or tenancy | `security-reviewer` |
| Tests: unit, integration, coverage gaps | `test-master` |
| SQL, schema, index design | `sql-pro`, `postgres-pro` |
| Slow queries, execution plans | `database-optimizer` |
| Celery task, beat schedule, background work | `python-pro` + `celery` docs via Context7 |
| Channels consumer, WebSocket routing | `websocket-engineer` |
| Docker, CI/CD, Kubernetes, process manager | `devops-engineer` |
| Terraform | `terraform-engineer` |
| Dashboards, alerts, OpenTelemetry, Sentry wiring | `monitoring-expert`, `sre-engineer` |
| Refactoring or deleting an existing system | `legacy-modernizer`, `spec-miner` |
| Reviewing your own diff before finishing | `code-reviewer` |
| Full-stack feature spanning both tiers | `fullstack-guardian` |
| Challenging a risky design before implementing | `the-fool`, `architecture-designer` |

Skills not listed above may be used when relevant. List the skills you loaded in
your final report.

### Step 3 — Then implement

Follow existing conventions exactly (§4–§6). Match the surrounding code's
naming, comment density, and error handling. Consistency beats personal
preference.

---

## 2. Repository layout

```text
mediflowOS-hmis/
├── backend/
│   ├── apps/                    # domain apps — one folder per bounded context
│   │   ├── identity_tenancy/    #   tenants, facilities, departments, wards, beds
│   │   ├── patient_registry/    #   patients, UHID, intake points, QR codes
│   │   ├── opd/ ipd/ emergency/ icu/ ot/
│   │   ├── lis/ ris/ pharmacy/ blood_bank/
│   │   ├── billing_insurance/ emr/ quality_os/
│   │   ├── abdm_gateway/ integration/
│   │   ├── audit/ platform/ realtime/ workers/
│   │   └── common/              # shared API routes (health probe)
│   ├── common/                  # cross-cutting policies, NOT a Django app
│   │   ├── tenant.py            #   TenantMiddleware, set_config binding
│   │   ├── audit.py             #   audit primitives
│   │   ├── throttling.py        #   AbdmHipThrottle
│   │   └── postgres/            #   schema-qualified table support
│   ├── config/
│   │   ├── settings/            #   base, dev, production, test
│   │   ├── asgi.py, urls.py
│   ├── workers/celery.py
│   ├── requirements.txt, requirements-dev.txt, pyproject.toml
│   └── manage.py
├── frontend/
│   └── src/                     # modules/, components/, lib/, stores/,
│                                # styles/, test/, App.tsx, main.tsx
├── tests/                       # pytest suite (outside backend/)
│   ├── unit/  integration/
├── docs/                        # PRD, SRS, Architecture, Quality OS catalog
├── docker/  terraform/
└── README.md
```

**Authoritative documents** (read before domain work; requirement IDs like
`TEN-010`, `REG-001`, `AUD-002`, `INT-012` are quoted in code comments and must
be honoured):

- `docs/SaaS HMIS Architecture v0.6.md` — §6 modules, §7 multi-tenancy,
  §8 ABDM, §14 frontend, §15 deployment, §16 observability
- `docs/SaaS HMIS PRD v0.5.md` — product intent
- `docs/SaaS HMIS SRS v0.5.md` — functional requirements by ID
- `README.md` — dependency version policy and setup

---

## 3. Tech stack (pinned — do not drift)

**Backend:** Python 3.11+, Django 5.2 LTS, DRF 3.18, PostgreSQL 15+ (psycopg 3),
Redis, Celery 5.6 + django-celery-beat, Channels 4.3, **daphne 4.2** (ASGI
server), SimpleJWT, django-otp, drf-spectacular, OpenTelemetry + Sentry.

**Frontend:** React 18.3, TypeScript 5.9, Vite 6.4, **React Router 7.18**
(`react-router-dom` — installed and in use), TanStack Query 5.104, Zustand,
React Hook Form 7.89 + Zod 3.25 (both wired in `src/modules/auth/LoginPage.tsx`),
Tailwind CSS v4 + shadcn/ui (vendored components in `src/components/ui/`),
Radix UI primitives, `lucide-react` icons. **Ant Design was removed** on
2 Oct 2026 (README §"UI system migration"); `antd`, `@ant-design/icons` and
`@ant-design/charts` are no longer dependencies and docs describing their API
do not apply to this repo.

**Dependency rules:**

- Never run `npm audit fix --force`, `pip install -U`, or a blanket major
  upgrade. Stay inside the current major; take the newest patch.
- `backend/requirements.txt` and `backend/pyproject.toml` must stay
  **synchronized** — edit both in the same commit.
- `opentelemetry-instrumentation-django` is pinned exactly (`==0.66b0`). It is a
  prerelease; upgrade it only in lockstep with the OTel packages.
- Channels and channels-redis stay on the same version.
- `daphne` is the ASGI server and is **not optional**. The project serves
  Channels WebSocket consumers, which a WSGI server cannot handle. Start the
  application with `daphne -b 0.0.0.0 -p 8000 config.asgi:application`, as
  `docker/Dockerfile.backend` does.
- Before adding any dependency, check `README.md` §"Dependency version
  guidance", then verify via Context7, then justify it in your report.
- Unused **backend** dependencies (`Pillow`, `openpyxl`, `reportlab`, `httpx`,
  `opentelemetry-sdk`, `opentelemetry-instrumentation-django`, `sentry-sdk`) are
  declared but not imported; each backs a documented requirement that is not
  implemented. On the **frontend**, `react-hook-form` and `zod` are wired
  (login form); `@ant-design/charts` was removed with the shadcn migration.
  The frontend dependencies that are declared but never imported are the
  shadcn prerequisites for components not yet vendored — nine Radix packages
  (`react-accordion`, `react-alert-dialog`, `react-checkbox`,
  `react-collapsible`, `react-popover`, `react-radio-group`, `react-select`,
  `react-switch`) and `sonner`. Do not build features on an unwired
  dependency silently — flag it. `zustand` and `react-router-dom`
  are wired: `src/stores/authStore.ts` and `src/App.tsx` / `src/main.tsx`
  respectively. `tests/unit/test_dependency_wiring.py`
  enforces this for the backend: a declared dependency that is neither
  imported, run as a process, nor listed in that test's `UNIMPLEMENTED` map
  fails the suite.
- `python-jose`, `python-dotenv` and `pydantic` were removed. Do not reintroduce
  them: SimpleJWT signs with PyJWT, and settings read `os.getenv` directly.
  `python-jose` in particular carries published CVEs.

### Documentation of tech & dependency changes (mandatory)

Any change to backend or frontend **technology, framework, library, tool, or
dependency** — including adds, removals, upgrades (even patch), pins, and
configuration changes (e.g. `vite.config.ts`, `tsconfig.json`,
`pyproject.toml`, `requirements*.txt`, `package.json`, `package-lock.json`,
Dockerfile base images, CI images) — is a **documentation-bearing change**.
For every such change the agent MUST update **all relevant documents** in the
same commit/PR. There is no "code-only" tech change.

**Authoritative documents that must be kept in sync:**

- `AGENTS.md` §3 — the pinned stack summary (`Backend:` / `Frontend:` lines).
- `README.md` — `## Tech stack` and `## Dependency version guidance` (tables,
  version numbers, and compatibility notes).
- `docs/SaaS HMIS Architecture v0.6.md` — §15 deployment, §14 frontend,
  and any technology table or diagram that names the changed component.
- `frontend/package.json` / `frontend/package-lock.json` and
  `backend/requirements.txt` / `backend/pyproject.toml` / `backend/requirements-dev.txt`
  — the source of truth; docs must match them.
- `docker/` and `terraform/` — base images, build args, or provider versions
  if the change touches the runtime or infra.
- `docs/` ADRs or decision logs — add or update an ADR when the change is
  architectural (new framework, major version, or pattern shift).

**Minimum required updates per change:**

1. Bump the version / name in `AGENTS.md` §3 **and** `README.md` dependency
   tables in the same commit that changes the manifest/lockfile.
2. If the change adds or removes a dependency, update the prose lists in both
   files and note whether the dependency is wired or currently unused (see the
   "Unused dependencies" rule above and `tests/unit/test_dependency_wiring.py`).
3. If the change alters setup, build, or run steps, update `README.md`
   prerequisites/setup and `AGENTS.md` §8 Commands.
4. If the change affects deployment, observability, or the PWA/offline plan,
   update the corresponding Architecture doc section.
5. Record the rationale, alternatives considered, and rollback plan in the PR
   description and — for non-trivial changes — in a short ADR under `docs/`.
6. Extend `Definition of done` (§9) and `Report format` (§10) evidence: the
   report MUST list every doc file touched for the tech/dependency change and
   the exact sections updated.

Failure to update the docs is a **process failure** even when the code and
tests are green. Reviewers must reject a PR that changes tech or dependencies
without the companion doc updates.

---

## 4. Backend rules (Django / DRF)

### Tenant isolation — highest severity

This is a multi-tenant clinical system holding PHI. Cross-tenant leakage is the
worst possible defect here.

- **Every tenant-owned model carries `tenant_id = models.UUIDField(db_index=True)`.**
  No exceptions.
- **Composite indexes lead with `tenant_id`.** Always:
  `models.Index(fields=["tenant_id", <other fields>])`.
- **Never query tenant-owned data by primary key alone.** Scope through the
  current tenant. A `get_object_or_404(Patient, pk=pk)` with no tenant filter is
  a defect even though it "works".
- `TenantMiddleware` binds `app.tenant_id` / `app.facility_id` via
  `set_config(..., is_local=true)`. **The binding is only valid inside a
  transaction.** `ATOMIC_REQUESTS = True` is what keeps the view inside that
  transaction. Do not add `@non_atomic_requests`, do not commit early, do not
  move the binding outside the atomic block.
- Do not call `set_config` outside the middleware, and do not introduce a
  second tenant context mechanism.
- The app connects as a **non-owner role without `BYPASSRLS`** in production.
  Never write code that depends on bypassing RLS.
- WebSocket consumers must resolve the tenant from `self.scope["user"]` and
  close when absent. See `apps/realtime/consumers.py`.
- Cross-tenant isolation tests are part of CI. Add them for new tables.

### Schema-qualified tables

`common/postgres` extends the PostgreSQL backend so `db_table = "registry.patient"`
means table `patient` in schema `registry`.

- Always set an explicit `db_table` in `Meta`, schema-per-module:
  `identity.`, `registry.`, `opd.`, `ipd.`, `emergency.`, `icu.`, `ot.`, `lis.`,
  `ris.`, `pharmacy.`, `bbk.`, `billing.`, `emr.`, `quality.`, `audit.`,
  `integration.`, `platform.`
- A new module means a new schema; the schema editor emits `CREATE SCHEMA`.
- `quote_qualified` splits a dotted name **only** on an exact `db_table` match.
  Index and constraint names derived from `db_table` must never be split by
  hand — this is why index names carry a hash suffix. Let Django generate them.
- Primary keys are `models.UUIDField(primary_key=True, default=uuid.uuid4)`.

### Models

- `db_index=True` on every FK and every field used in a filter. Avoid
  `unique=True` across tenants unless globally unique (e.g. `Tenant.slug`).
- Use `models.JSONField` for semi-structured clinical payloads (`demographics`,
  `consent_flags`, `address`). Do not model volatile clinical shapes as columns.
- Migrations must be **backward compatible: expand, then contract.** Never drop
  or rename a column in the same release that stops writing it.
- Reference the governing requirement IDs in the model docstring, following
  existing style: `"""Patient registry models (REG-001 to REG-013 ...)."""`
- Never edit an applied migration. Add a new one.

### Permissions — deny by default

`REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] = [IsAuthenticated]`.

- **Never** add `AllowAny` to a tenant-owned endpoint.
- Only two endpoints may opt out: the health probe
  (`apps/common/urls.py`) and the ABDM callback, which carries no user JWT.
- The ABDM callback (`ABHACallbackViewSet` in `apps/abdm_gateway/views.py`)
  is **implemented** — it authenticates presence, validates timestamps, binds
  the tenant from `Facility.abdm_hip_id`, is idempotent on the gateway
  request ID, matches patients by ABHA then demographics, issues an OPD
  token, and returns an acknowledgement carrying the consent event. There is
  no `501` anywhere under `backend/apps/`.
  Residual §8.4 gaps that must not be papered over (and must not be reported
  as done): signature verification is **presence-only** (any
  `X-ABDM-Signature`/`Bearer` header passes — ABD-005), the consent event is
  built but **not persisted** (ABD-011), and the link token is
  `secrets.token_urlsafe(32)` with no encryption (ABD-012 placeholder).
  Do not regress the endpoint to 501, and do not claim these three are
  finished until the code says so.
- `tests/integration/test_api_authentication.py` enforces this. Keep it passing.

### Serializers

- `ModelSerializer` with explicit `fields`, not `"__all__"`, on new code.
- Declare `read_only_fields` for `id`, `created_at`, and server-owned values.
- Never expose a password hash, token, or internal RLS context field.
- Validate business rules in the serializer or service, not in the view.

### Views and URLs

- `viewsets.ModelViewSet` per resource, router-registered in the app's
  `urls.py` with an `app_name` namespace, wired in `config/urls.py` under
  `/api/v1/`.
- Use `perform_create` / `get_queryset` hooks for tenant scoping — not
  per-method overrides.
- Custom actions use `@action`; document them and mark the schema with
  `@extend_schema` so `/api/docs/` stays accurate.
- Return `409`/`422`-class semantics deliberately; do not blanket-catch
  `Exception` and return `400`.
- Raise DRF's exception classes (`NotFound`, `PermissionDenied`,
  `ValidationError`). No bare `except Exception: return Response(..., 400)`.
- Serialize validation with `serializer.is_valid(raise_exception=True)`.
- Never swallow an exception silently. If a failure is intentionally
  tolerated, log it with context.

### Docstring and comment discipline

This repo documents **why**, not what, and it is meticulous about it. Follow it:

- Module docstring states the requirement IDs or the mechanism.
- Any non-obvious decision gets a comment explaining the failure it prevents.
  Example from `common/tenant.py`: explain that `set_config(..., is_local=true)`
  in autocommit is silently discarded, so the binding must live inside the
  request transaction.
- Do not add comments that merely restate the code.
- Do not claim something works when it does not. If a feature is partial, say so
  in the docstring and return an explicit failure status — as
  `ABHACallbackViewSet` does.

### Async and background work

- `workers/celery.py` holds the Celery app. Tasks take explicit `tenant_id`
  arguments — a task must never run without tenant context.
- Tasks that need database tenant context must open their own
  `transaction.atomic()` and call `set_tenant_context` inside it.
- `CELERY_TASK_ALWAYS_EAGER = True` in dev and test settings. Keep it true there.
- Requests must stay fast. Anything slow (indicator computation, report
  generation, ABDM sync, exports) belongs in a task. `reportlab`, `openpyxl` and
  `httpx` are present for exactly this.
- Tasks need real retry policy and idempotency. A retried task must not
  double-write.

### Security

- JWT auth via SimpleJWT. Never write a custom token scheme.
- Throttle ABDM callbacks with `AbdmHipThrottle`, keyed per HIP ID. Do not let
  them draw down the shared anonymous budget.
- Secrets come from environment variables. Never hardcode a key, password, or
  patient data. `SECRET_KEY` has a `"change-me"` default that must never reach
  production — `config/settings/production.py` is still a placeholder and
  hardening it is in scope when you touch deployment.
- Log identifiers, not PHI. No patient names, diagnoses, or identifiers in log
  lines.
- DPDP Act applies: record consent with timestamp, source app, and purpose.
- Write SQL through the ORM or parameterized queries. No string-formatted SQL
  with user input.

---

## 5. Frontend rules (React 18 / TypeScript / Tailwind + shadcn/ui)

### TypeScript

- `strict: true` is on. Never introduce `any`, `as any`, or `@ts-ignore` to
  make a type error go away. Fix the type.
- `isolatedModules` and `verbatimModuleSyntax`-style imports: use
  `import type { Foo }` for type-only imports.
- Alias `@/*` maps to `src/*` in both `tsconfig.json` and `vite.config.ts`. Use
  it; do not write `../../../src/lib/health`.
- Prefer discriminated unions over optional-field soup for API payloads.
- Keep API response types next to the fetch function.

### Components

- Functional components with hooks only. No class components.
- `React.StrictMode` is on: **effects must be idempotent and clean up
  properly.** Every subscription, timer, and listener gets a teardown.
- Never fetch inside `useEffect` for data the component renders. Use
  TanStack Query. Fetch effects are for genuine side effects only.
- Do not destructure `useState` into a mutable object; use functional updates
  (`setX(prev => ...)`) so updates compose.
- Memoize expensive derivations (`useMemo`) and passed callbacks
  (`useCallback`) only where measured or where identity is a real dependency.
- Component-level state stays local. Do not prop-drill beyond two levels; use
  composition or context.
- Split a component when it exceeds a readable single screen, and when you split,
  colocate the sub-component rather than creating a shallow wrapper chain.

### UI system (Tailwind v4 + shadcn/ui — Ant Design is gone)

- The theme lives in `src/styles/globals.css`: design tokens are CSS custom
  properties registered under `@theme inline` (brand primary
  `hsl(174 83% 25%)`, teal `#0f766e`). Do not hardcode colors inline; add or
  reuse a token.
- Use the vendored shadcn components in `src/components/ui/` before writing
  custom ones. To vendor a new one: `npx shadcn@latest add <component> --diff`,
  then commit the generated source — never overwrite local edits.
- Import icons from `lucide-react` (shadcn's `iconLibrary`), never from a
  CDN or a hand-rolled SVG asset.
- Accessibility is a requirement, not a nicety: `aria-label` on every
  icon-only `Button`, keyboard-reachable interactions, and labels on inputs.
- Responsive: Tailwind breakpoints (`sm:`/`md:`/`lg:`/`xl:`) plus the
  `useBreakpoint` hook (`src/lib/`) for behaviour changes, not only layout.
  Hospital screens are often small or wall-mounted.

### Data fetching

- TanStack Query owns all server state. `QueryClientProvider` lives in
  `src/App.tsx` (one `QueryClient` at module scope); never create a second
  `QueryClient` in app code.
- Query keys must be structured arrays, scoped and stable:
  `["patients", tenantId, filters]`. Include every input that changes the result.
- Set `retry`, `refetchInterval`, `staleTime` deliberately. The health query
  uses `retry: false, refetchInterval: 30_000` — mirror that reasoning.
- Mutations invalidate the affected query keys. Optimistic updates only where
  rollback is trivially correct.
- Throw a real `Error` from the fetch layer on `!response.ok`. Show failures to
  the user; never let a query fail silently.
- Keep fetch functions in `src/lib/`. The existing `src/lib/health.ts` is the
  pattern: exported interface, named function, `throw` on failure.
- Zustand is for cross-cutting client UI state only, never as a server-state
  cache.

### Routing and structure

Architecture doc §14 requires per-module folders with **route-level code
splitting**. The layout is `src/modules/<backend_module>/`, mirroring the backend
app names (`src/modules/auth/`, `src/modules/patient_registry/`,
`src/modules/dashboard/`) — `src/modules/`, not `src/features/`. When adding a
module, create its folder there rather than growing `src/App.tsx`; `App.tsx` is
the authenticated shell and route table only.

Routing is **React Router 7** (`react-router-dom`), installed and in use:
`BrowserRouter` in `src/main.tsx`, the route table and `/*` auth guard in
`src/App.tsx`. Add new routes there, keep the `/login` and `/*` guard structure
intact, and remember that a nav entry with no matching `<Route>` renders a blank
content area — mark it `disabled` until its module exists. Lazy-load module
routes rather than importing them eagerly. Read the current docs via Context7
(`/remix-run/react-router`, `/websites/reactrouter`) before using an unfamiliar
router API.

### PWA and offline (architecture doc §14)

Not yet implemented. If you touch it: a clinical order must never render as
"saved" until the server confirms, and offline drafts need a visible unsynced
state. The counter/token display route is intentionally **REST polling, not
Channels**.

---

## 6. Testing rules

**Backend (pytest):**

- Tests live in `tests/`, not inside backend packages.
- Mark every test `@pytest.mark.unit` or `@pytest.mark.integration`;
  `--strict-markers` is on.
- `config.settings.test` uses in-memory SQLite and needs **no external
  services**. Keep it that way — do not add a test that requires PostgreSQL
  unless it skips cleanly.
- Tests that genuinely need PostgreSQL (RLS, `set_config` transaction
  behaviour) go through the `requires_postgres` gate in
  `tests/integration/test_postgres_schema.py`, driven by `MEDIFLOW_TEST_PG*`
  env vars, and skip otherwise.
- `ATOMIC_REQUESTS` is `False` in test settings deliberately. The production
  value is asserted in `tests/unit/test_project_settings.py` — do not "fix"
  this inconsistency.
- **A test that passes against a mocked mechanism is not proof the mechanism
  works.** The tenant middleware tests exist because the original bug was
  invisible to unit tests. Assert the real coupling wherever possible.
- Docstrings should state what the test pins down and why it exists.

**Frontend (Vitest + Testing Library):**

- `*.unit.test.ts` for pure logic; `*.integration.test.tsx` for component
  flows. Both patterns are established — follow them.
- Test behaviour and user-visible output, not implementation internals.
- Use `screen.getByRole` / `getByText` over test IDs. `getByRole` proves
  accessibility as a side effect.
- Stub `fetch` with `vi.stubGlobal` and `vi.unstubAllGlobals()` in `afterEach`.
- Wrap component-under-test in a `QueryClientProvider` with
  `defaultOptions: { queries: { retry: false } }` so tests do not hang on
  retries.
- `matchMedia` is already stubbed in `src/test/setup.ts`. Extend it there
  rather than per test file.

---

## 7. Code style

**Python:** ruff, line length **100**, target py311. Ruff rules `E4`, `E7`,
`E9`, `F`. Google-style docstrings. `black` is configured in `pyproject.toml`
but **not installed** — do not run it; match the existing formatting by hand.

**TypeScript/TSX:** 2-space indent. `strict` mode. No semicolonless style —
existing files use semicolons and double quotes. Match the file you are editing.

**Commits:** Conventional Commits, as in the existing history:
`feat(security): ...`, `fix(security): ...`, `chore: ...`. Scope the type.
Security and tenant-isolation fixes must be scoped `security`.

---

## 8. Commands

**Backend** (from `backend/`, venv active):

```bash
python manage.py migrate
python manage.py makemigrations <app>
python manage.py runserver 0.0.0.0:8000
python manage.py spectacular --file schema.yml     # verify the OpenAPI schema
celery -A workers worker -l info
celery -A workers beat -l info
```

**Tests and lint** (from `backend/`):

```bash
python -m pytest                        # full suite, no services needed
python -m pytest -m unit
python -m pytest -m integration
python -m ruff check . ../tests         # must be clean
```

**Frontend** (from `frontend/`):

```bash
npm ci
npm run dev
npm run lint
npm run typecheck
npm run test
npm run check        # lint + typecheck + test — the full gate
npm run build
npm run test:coverage
```

---

## 9. Definition of done

Before reporting a task complete, verify all of the following and state the
results:

1. **Context7 was used** for every library API involved. List the IDs queried.
2. **Skills were loaded.** List the skill IDs used.
3. `python -m ruff check . ../tests` is clean.
4. `python -m pytest` passes.
5. `npm run check` passes (lint + typecheck + tests).
6. New migrations are generated, backward compatible, and included.
7. New/changed tenant-owned endpoints have isolation coverage and remain
   deny-by-default.
8. `/api/schema/` still generates without warnings.
9. No secrets, PHI, or debug statements were introduced.
10. **Docs are in sync for any tech/dependency change** — `AGENTS.md` §3,
    `README.md` (Tech stack + Dependency version guidance), the relevant
    `docs/*.md` sections, and manifests/lockfiles all agree on versions and
    wiring status. See §3 "Documentation of tech & dependency changes" for
    the full checklist. A green test suite does not excuse stale docs.
11. Unfinished work is stated plainly — never report a partial implementation
    as complete. If something is blocked, say which requirement ID and what is
    missing.

## 10. Report format

End every task with:

- **What changed** — files and intent.
- **Verification** — the commands you ran and their actual results. Never
  claim a command passed without running it.
- **Context7** — library IDs queried.
- **Skills** — skill IDs loaded.
- **Docs updated** — for any backend/frontend tech or dependency change, list
  every document and section updated (`AGENTS.md` §3, `README.md` Tech stack /
  Dependency version guidance, `docs/...` §, manifests/lockfiles). If no tech
  or dependency changed, state "No tech/dependency change — no doc sync
  required." This item is mandatory.
- **Not done** — anything incomplete, blocked, or deliberately deferred, with
  the requirement ID.
- **Notes** — dependency changes, doc updates, or risks worth the reviewer's
  attention.

## 11. Prohibited

- Silently upgrading a dependency or breaking a version pin.
- Changing backend or frontend tech / dependencies (add, remove, upgrade, pin,
  or config) without updating **all relevant documents and `README.md`** per
  §3 "Documentation of tech & dependency changes" — stale docs are a
  process failure even when tests pass.
- Adding `AllowAny`, a second tenant context mechanism, or an unauthenticated
  tenant-owned endpoint.
- Returning `200` from the ABDM callback before its seven §8.4 requirements are
  met.
- Deleting or weakening `tests/integration/test_api_authentication.py` or any
  tenant-isolation test.
- Rewriting an applied migration, or a destructive one without an expand/contract
  plan.
- Committing `venv/`, `node_modules/`, `dist/`, `.coverage`, `.env`, or any
  secret.
- Claiming verification you did not run.