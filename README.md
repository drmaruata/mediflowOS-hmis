# Mediflow OS HMIS

Mediflow OS HMIS is a multi-tenant healthcare management information system designed for hospitals and clinics. The project combines a Django-based backend API with a Vite + React frontend to deliver modules for patient administration, operations, billing, pharmacy, reporting, quality indicators, and integration workflows.

This repository is organized as a modular monolith, with the backend split into domain apps and the frontend built as a single-page application.

## Project overview

The application is built around the following principles:

- Multi-tenant healthcare workflows and tenant-aware data access
- Modular domain structure for clinical and operational areas
- REST API-first backend using Django REST Framework
- Realtime features using Django Channels and Redis
- Background jobs and scheduling through Celery and Redis
- PostgreSQL as the primary data store
- React frontend with Shadcn UI (Tailwind CSS) and Vite for a modern admin interface

## Tech stack

### Backend
- Python 3.11+
- Django 5.2 LTS
- Django REST Framework
- PostgreSQL 15+
- Redis
- Celery + django-celery-beat
- Django Channels
- JWT authentication
- Field-level encryption at rest (`cryptography`, AES-GCM tokens + keyed-HMAC
  search indexes) for patient identifiers (REG-008)
- OpenAPI schema generation via drf-spectacular
- OTP support via django-otp

### Frontend
- React 18
- TypeScript
- Vite 6
- **Shadcn UI** on Tailwind CSS v4 (components vendored into `src/components/ui/`)
- Radix UI primitives (unstyled accessible bases)
- `lucide-react` (icons)
- React Router 7
- TanStack Query 5
- Zustand
- Zod + React Hook Form

### Infrastructure / platform
- Redis for caching, broker, and channel layer
- PostgreSQL for application persistence
- ASGI application server support via Django Channels
- Modular app layout under `backend/apps/`

## Dependency version guidance

Versions below were checked against npm and PyPI on 2026-10-02 and re-verified against the current lockfiles/manifests (frontend/package-lock.json lockVersion 3, 188,202 B; backend/requirements.txt ↔ backend/pyproject.toml synchronized). Prefer the newest patch release within the currently tested major; do not use `npm audit fix --force` or blanket major upgrades as a routine update. Coordinate major upgrades with the compatibility checks in this README.

### Frontend dependencies

| Dependency | Installed | Latest | Recommendation |
| --- | --- | --- | --- |
| `react`, `react-dom` | 18.3.1 | 19.3.0 | Keep React 18 until React 19 is tested with shadcn/ui and the full UI. |
| `@types/react`, `@types/react-dom` | 18.3.31, 18.3.7 | 19.3.0 | Keep aligned with React 18; upgrade with React, not independently. |
| `tailwindcss`, `@tailwindcss/vite` | 4.1.11 | 4.1.11 | Current latest; used via the Vite plugin, no `tailwind.config.js`. |
| `lucide-react` | 0.525.0 | 0.525.0 | Replaces `@ant-design/icons`. Keep aligned with shadcn's `iconLibrary` in `components.json`. |
| `@radix-ui/react-*` | see `package.json` | — | Unstyled primitives shadcn composes. Upgrade the whole set together. |
| `class-variance-authority` | 0.7.1 | 0.7.1 | Variant system for vendored shadcn components. |
| `tailwind-merge`, `clsx` | 3.3.1, 2.1.1 | — | Back `cn()` in `src/lib/utils.ts`. |
| `sonner` | 2.0.6 | 2.0.6 | Toast notifications (declared; a Radix toast component is vendored instead — see below). |
| `@tanstack/react-query` | 5.104.0 | 5.104.0 | Current latest and used by the app. |
| `react-router-dom` | 7.18.4 | 7.18.4 | Current latest in v7 and used by the app for routing; keep in step with `react-router`, which it pins exactly. |
| `zustand` | 4.5.7 | 5.0.15 | Used by `src/stores/authStore.ts`. Defer v5 until the store's usage is re-tested against it. |
| `react-hook-form`, `@hookform/resolvers` | 7.89.0, 3.10.0 | — | **Now wired** by the login form (`src/modules/auth/LoginPage.tsx`). |
| `zod` | 3.25.76 | 4.6.5 | **Now wired** for login-form validation. Defer the v4 schema migration. |
| `vite` | 6.4.3 | 8.3.2 | Current patched v6 is clean; plan an upgrade to v8 and verify plugins and aliases. |
| `@vitejs/plugin-react` | 4.7.0 | 6.1.1 | Keep compatible with Vite 6 now; upgrade with Vite when moving to v8. |
| `typescript` | 5.9.3 | 7.0.2 | Keep v5 for now; current typescript-eslint does not support TypeScript 7 yet. |
| `vitest`, `@vitest/coverage-v8` | 3.2.4 | — | Test runner and coverage provider. |
| `eslint` + typescript/react plugins | 9.29.0 | — | Lint gate for `npm run check`. |

`react-router-dom` (7.18.4) is installed and used: `BrowserRouter` in
`frontend/src/App.tsx`, the route table and auth guard in the same file, and
`MemoryRouter` in the tests. `react-hook-form` and `zod` are now genuinely
imported by the login form, so they are no longer "declared but unused".

### UI system migration: Ant Design 5 → Shadcn UI (2 Oct 2026)

The frontend `frontend/` folder was deleted and re-scaffolded. Ant Design,
`@ant-design/icons`, and `@ant-design/charts` were **removed** and replaced
with Shadcn UI on Tailwind CSS v4. Rationale and the full decision table are
in `docs/SaaS HMIS Architecture v0.6.md` §14.1.

| Removed | Added | Why |
| --- | --- | --- |
| `antd` | `tailwindcss` + `@tailwindcss/vite` | Components are vendored source, not a compiled dependency; Tailwind owns the token system. |
| `@ant-design/icons` | `lucide-react` | Matches shadcn's default `iconLibrary`. |
| `@ant-design/charts` | *(nothing)* | Dashboard donut/bar charts are hand-rolled inline SVG, so no chart dependency is needed at all. |
| — | `@radix-ui/react-*` | Unstyled accessible primitives shadcn builds on. |
| — | `class-variance-authority`, `tailwind-merge`, `clsx` | Variant system and `cn()` class merging for the vendored components. |
| — | `components.json`, `src/components/ui/` | shadcn registry config plus the vendored component source. |

**Breaking change for contributors.** shadcn components are *source files you
own*, not a package you import. Upstream changes arrive only via
`npx shadcn@latest add <component> --diff`; never overwrite local edits without
reviewing the diff.

`sonner` is declared but the vendored Radix `Toast` component is used instead;
treat `sonner` as unused until a toast call site is written.

**Added shadcn components** (vendored in `frontend/src/components/ui/`):
`button`, `card`, `input`, `label`, `badge`, `avatar`, `dialog`, `tabs`,
`tooltip`, `dropdown-menu`, `toast`, `scroll-area`, `progress`, `separator`.

**Removed dependencies:** `antd`, `@ant-design/icons`, `@ant-design/charts`,
`tailwindcss-animate` was also dropped in favour of Tailwind v4's built-in
animation utilities.

### Backend dependencies

| Dependency | Installed | Latest | Recommendation |
| --- | --- | --- | --- |
| Django | 5.2.17 | 6.1.1 | Stay on the 5.2 LTS line; plan and test a Django 6 migration separately. |
| Django REST Framework | 3.18.1 | 3.18.1 | Current latest. |
| django-cors-headers | 4.9.0 | 4.9.0 | Current latest. |
| djangorestframework-simplejwt | 5.5.1 | 5.5.1 | Current latest. |
| django-otp | 1.7.3 | 1.7.3 | Current latest. |
| drf-spectacular | 0.30.0 | 0.30.0 | Current latest. |
| psycopg | 3.3.6 | 3.3.6 | Current latest; use psycopg 3, not psycopg2. |
| redis | 8.1.0 | 8.1.0 | Current latest. |
| celery | 5.6.3 | 5.6.3 | Current latest. |
| django-celery-beat | 2.9.0 | 2.9.0 | Current latest. |
| channels, channels-redis | 4.3.2, 4.3.0 | 4.3.2, 4.3.0 | Current latest; keep the pair aligned. |
| daphne | 4.2.3 | 4.2.3 | ASGI server; required because the project serves Channels WebSocket consumers. See below. |
| cryptography | 48.0.0 | 48.0.0 | Application-level field encryption at rest (REG-008): AES-256-GCM tokens + keyed-HMAC search indexes for patient identifiers. **Pinned exactly** — the token format and key derivation depend on the installed release. Wired via `common/crypto.py`. |
| openpyxl | 3.1.5 | 3.1.5 | Current latest in the supported 3.1 line; currently unused — see below. |
| Pillow | 12.3.0 | 12.3.0 | Current latest; currently unused — see below. |
| reportlab | 5.0.1 | 5.0.1 | Current latest; currently unused — see below. |
| httpx | 0.28.1 | 0.28.1 | Current latest in the supported 0.28 line. Wired via `apps/abdm_gateway/client.py` — outbound ABDM sandbox ABHA create/verify (REG-009). |
| opentelemetry-sdk | 1.45.0 | 1.45.0 | Current latest; keep aligned with instrumentation. Currently unwired. |
| opentelemetry-instrumentation-django | 0.66b0 | 0.66b0 | Prerelease; keep exactly pinned and upgrade with matching OTel packages. Currently unwired. |
| sentry-sdk | 2.71.0 | 2.71.0 | Current latest in v2. Currently unwired. |

The backend environment also reported newer transitive `cron-descriptor` releases. Let the parent package resolve compatible updates; `django-celery-beat` currently constrains `cron-descriptor` below v2. Keep runtime constraints in `backend/requirements.txt` and `backend/pyproject.toml` synchronized.

### daphne (added during the tenancy and security hardening pass)

`daphne` is the ASGI server the application runs behind, and it is declared in
both `backend/requirements.txt` and `backend/pyproject.toml` as `>=4.2,<5`,
resolving to 4.2.3.

It was previously missing entirely: the project declares `ASGI_APPLICATION` and
serves Django Channels consumers for notifications and live vitals
(architecture doc section 13), but no ASGI server was installed or declared. A
WSGI server cannot serve a WebSocket consumer, so the image had no valid way to
start. `docker/Dockerfile.backend` uses it as the entrypoint.

If you run the application locally, start it with daphne rather than
`runserver`:

```bash
# From backend/, with the virtualenv active:
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

`python manage.py runserver` still works for ordinary HTTP development through
Django's ASGI handler, but it is not what the container uses.

### Dependencies that are declared but not yet used

`Pillow`, `openpyxl`, `reportlab`, `opentelemetry-sdk`,
`opentelemetry-instrumentation-django` and `sentry-sdk` are declared but not
imported anywhere in `backend/`. Each backs a documented requirement that is not
implemented yet:

| Package | Backs |
| --- | --- |
| `Pillow` | printable facility/counter QR codes (architecture doc 8.4) |
| `openpyxl`, `reportlab` | Quality OS regulatory exports (9.9) |
| `opentelemetry-*`, `sentry-sdk` | observability (16) — entirely unimplemented |

They are kept pinned rather than removed so the versions are not re-resolved
later. `tests/unit/test_dependency_wiring.py` fails if a declared dependency is
neither imported, deliberately run as a process, nor listed in that test's
`UNIMPLEMENTED` map with the requirement it serves — so this section cannot go
stale without a test failing.

### Dependencies removed during the hardening pass

`python-jose`, `python-dotenv` and `pydantic` were removed:

- `python-jose` was redundant — SimpleJWT signs and verifies with PyJWT — and
  carries known published CVEs.
- `python-dotenv` was never loaded; settings read `os.getenv` directly.
- `pydantic` had no consumer; Django and DRF do not use it.

No frontend dependency was removed in that pass. An earlier note here stated that
`react-router` had been removed from the frontend; that was inaccurate — the
current source uses `react-router-dom` 7.18.4 (see the frontend table above).

## Repository structure

```text
mediflowOS-hmis/
├── backend/
│   ├── apps/
│   ├── common/                    # tenant, rls, authentication, throttling
│   │   └── postgres/              # schema-qualified table support
│   ├── config/
│   │   └── settings/              # base, dev, production, test
│   ├── workers/
│   ├── manage.py
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pyproject.toml
│   └── scripts/                   # migration and traceability generators
├── frontend/
│   ├── src/
│   │   ├── modules/              # one folder per backend module (auth, dashboard, ...)
│   │   ├── lib/                  # fetch wrappers, e.g. health.ts
│   │   ├── stores/               # zustand client UI state
│   │   ├── styles/               # globals.css owns the Tailwind/shadcn tokens
│   │   ├── components/           # AppShell + vendored shadcn ui/ components
│   │   ├── test/                 # vitest setup (matchMedia, ResizeObserver)
│   │   ├── App.tsx               # route table + QueryClientProvider
│   │   └── main.tsx
│   ├── index.html                # dark-mode pre-paint bootstrap
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
├── docs/
│   ├── SaaS HMIS Architecture v0.6.md
│   ├── SaaS HMIS PRD v0.5.md
│   ├── traceability.md            # generated; do not edit by hand
│   └── ...
├── tests/
│   ├── unit/
│   └── integration/
├── docker/
│   ├── Dockerfile.backend
│   ├── compose.yaml
│   └── .env.example
├── terraform/                     # empty; IaC not yet in scope
├── .github/workflows/ci.yml
├── .gitignore
└── README.md
```

## Prerequisites

Before setting up the project locally, install the following:

- Python 3.11 or newer
- Node.js 22.22.2+ or 24.15+ and npm (required by the frontend test environment)
- PostgreSQL 15+ (16 recommended). The schema relies on row-level security
  and on `NULLS NOT DISTINCT` unique constraints, both of which require
  PostgreSQL 15+; `docker/compose.yaml` and CI run PostgreSQL 16. On 14 or
  earlier Django silently omits the `NULLS NOT DISTINCT` constraint
  (system check `models.W047`), leaving token-series uniqueness unenforced.
- Redis
- Git
- A terminal such as PowerShell, Bash, or zsh

Optional but helpful:

- Docker Desktop (for container-based local development)
- pgAdmin or a SQL client for database inspection
- VS Code with Python and TypeScript extensions

## Backend setup

### 1. Create and activate a virtual environment

From the repository root:

```bash
cd backend
python -m venv venv
```

On Windows PowerShell:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
```

On macOS/Linux:

```bash
source venv/bin/activate
```

### 2. Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes runtime dependencies plus pytest, coverage, and Ruff. For a runtime-only installation, use `pip install -r requirements.txt`.

### 3. Configure PostgreSQL and Redis

The project defaults to PostgreSQL and Redis values in the Django settings. For local development, ensure PostgreSQL is running and a database exists, for example:

```sql
CREATE DATABASE mediflow_dev;
```

Set the environment variables you want your app to use before starting Django. Example:

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.dev"
$env:DJANGO_SECRET_KEY = "local-dev-secret-key"
$env:DJANGO_DEBUG = "true"
$env:PGDATABASE = "mediflow_dev"
$env:PGUSER = "postgres"
$env:PGPASSWORD = "postgres"
$env:PGHOST = "localhost"
$env:PGPORT = "5432"
$env:REDIS_URL = "redis://localhost:6379/0"
$env:CELERY_BROKER_URL = "redis://localhost:6379/0"
```

> **PATIENT_FIELDS_KEY (REG-008):** patient identifiers (`abha_number`,
> `abha_address`, `contact.mobile`) are encrypted at rest with a key derived
> from `PATIENT_FIELDS_KEY`. For local dev this is optional — `config.settings.dev`
> supplies a deterministic development passphrase when the variable is unset —
> but it must be explicitly exported in any non-DEBUG environment: `base.py`
> refuses to start without it so identifiers are never encrypted under an
> empty or guessed key. Example:
>
> ```powershell
> $env:PATIENT_FIELDS_KEY = "a-long-random-passphrase-only-the-hospital-knows"
> ```

> The project defaults to PostgreSQL on `localhost` and Redis at `redis://redis:6379/0` in many settings. If you are using local services instead of containers, update these values accordingly.

### 4. Run database migrations

```bash
cd backend
python manage.py migrate
```

### 5. Create a superuser

```bash
python manage.py createsuperuser
```

### 6. Start the backend development server

For ordinary HTTP development, `runserver` is enough:

```bash
python manage.py runserver 0.0.0.0:8000
```

To exercise the Channels WebSocket consumers (notifications and live vitals),
run the ASGI server instead — that is what the container uses:

```bash
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

The API should be available at:

- http://localhost:8000/admin/
- http://localhost:8000/api/schema/
- http://localhost:8000/api/docs/
- http://localhost:8000/api/v1/health/ — liveness, anonymous, no database needed
- http://localhost:8000/api/v1/health/ready/ — readiness, `503` if the database
  is unreachable

## Frontend setup

### 1. Install dependencies

From the repository root:

```bash
cd frontend
npm ci
```

### 2. Start the frontend dev server

```bash
npm run dev
```

By default, Vite will start a development server and print the local URL, typically:

- http://localhost:5173/

### 3. Build the frontend for production

```bash
npm run build
```

### 4. Preview the production build

```bash
npm run preview
```

## Running background workers

The project includes Celery support for asynchronous work such as indicator computations and integration tasks.

Start a Celery worker:

```bash
cd backend
celery -A workers.celery worker --loglevel=info
```

Start Celery Beat for scheduled tasks:

```bash
cd backend
celery -A workers.celery beat --loglevel=info
```

## Common Django commands

From the `backend` folder, these are the most useful commands:

```bash
# Show project status and configuration
python manage.py check

# Run migrations after model changes
python manage.py makemigrations
python manage.py migrate

# Collect static files for deployment
python manage.py collectstatic --noinput

# Run all backend tests (isolated SQLite settings; no PostgreSQL/Redis needed)
python -m pytest

# Run test tiers separately
python -m pytest -m unit
python -m pytest -m integration

# Run tests with coverage
python -m pytest --cov=apps --cov=common --cov=config --cov-report=term-missing

# Run backend lint and Django configuration checks
python -m ruff check . ../tests
python manage.py check --settings=config.settings.test

# Run a Django shell
python manage.py shell
```

## Common frontend commands

From the `frontend` folder:

```bash
# Start Vite dev server
npm run dev

# Run lint, type-check, and all frontend tests
npm run check

# Run individual checks
npm run lint
npm run typecheck
npm run test:unit   # vitest run "src/**/*.unit.test.ts" (glob by file naming convention)
npm run test:integration  # vitest run "src/**/*.integration.test.tsx"
npm run test:coverage

# Build the project
npm run build

# Preview the production build locally
npm run preview
```

## Suggested local workflow

For standard development, use this flow:

1. Start PostgreSQL and Redis locally.
2. Activate the backend virtual environment.
3. Run `python manage.py migrate`.
4. Start the Django server with `python manage.py runserver 0.0.0.0:8000`
   (or `daphne -b 0.0.0.0 -p 8000 config.asgi:application` for WebSockets).
5. Start Celery worker(s) if background jobs are needed.
6. Start the frontend with `npm run dev`.
7. Open the frontend in the browser and verify API calls through the Django backend.

For local validation, run `npm run check` from `frontend/`, and run `python -m pytest` plus `python -m ruff check . ../tests` from `backend/`. Pytest uses `config.settings.test` with in-memory SQLite and does not need external services.

## Notes on architecture

This repository follows a modular monolith design:

- Domain logic is grouped under `backend/apps/`
- Shared policies live in `backend/common/`
- Tenant-aware middleware and utilities handle cross-cutting concerns
- API schema is generated from DRF endpoints with `drf-spectacular`
- Realtime and cache concerns rely on Redis
- Clinical and operational services are organized by module like `patient_registry`, `opd`, `ipd`, `pharmacy`, `lab`, `billing`, and `quality_os`

## Troubleshooting

### Database connection errors

Verify that PostgreSQL is running and your environment variables match your local database credentials.

### Redis connection errors

Check that Redis is installed and running locally, and confirm the `REDIS_URL` / `CELERY_BROKER_URL` values.

### Frontend cannot reach the backend

Make sure the frontend API base URL matches the backend. If your frontend is configured to call a different host, update the relevant configuration or proxy settings.

### Missing dependencies

If Python or npm packages are missing, reinstall them using:

```bash
pip install -r backend/requirements-dev.txt
npm ci --prefix frontend
```

## Production and deployment notes

This project is not yet a full production deployment template in the repository. For deployment, you should typically:

- Replace local environment variables with secure production values
- Configure a managed PostgreSQL database
- Configure a managed Redis instance
- Set `DJANGO_DEBUG=false`
- Use a production WSGI/ASGI deployment strategy
- Run `python manage.py collectstatic` for static asset serving
- Configure Celery workers and beat in a process manager or container orchestration layer
- Restrict CORS and trusted origins via environment settings

## Further reading

The project documentation in the `docs/` folder contains deeper product and architecture notes:

- `docs/SaaS HMIS Architecture v0.6.md`
- `docs/SaaS HMIS PRD v0.5.md`
- `docs/SaaS HMIS SRS v0.5.md`
- `docs/SaaS HMIS Quality OS Indicator Catalog v0.2.json`

## License

This project does not currently declare a license in the repository root. If this is intended for public distribution, add a license file and define the legal terms before publishing it externally.

## Summary

To start working on the project locally:

```bash
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

This will give you a working local backend and frontend for the Mediflow OS HMIS application.
