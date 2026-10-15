"""Shared Django settings."""
import os
from datetime import timedelta
from pathlib import Path

from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

from apps.abdm_gateway.client import require_sandbox_base_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "false") == "true"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

# REG-008: master passphrase for application-level field encryption
# (``abha_number``, ``abha_address``, ``contact.mobile``, AES-GCM via
# ``common.crypto``; PBKDF2-HMAC-SHA256 derives the AES and HMAC-SHA256 index
# keys). There is deliberately **no default**: encrypting patient identifiers
# under an empty or guessed passphrase would be theatre, so a non-DEBUG
# settings import refuses to start without it. dev.py and test.py supply
# deterministic values *before* they ``from .base import *``; production must
# set PATIENT_FIELDS_KEY in the environment.
PATIENT_FIELDS_KEY = os.getenv("PATIENT_FIELDS_KEY", "")
if not DEBUG and not PATIENT_FIELDS_KEY:
    raise ImproperlyConfigured(
        "PATIENT_FIELDS_KEY must be set when DEBUG is off: patient identifiers "
        "are encrypted at rest (REG-008) and must never be encrypted under a "
        "missing master key. dev.py/test.py set a value; production must export "
        "one."
    )

# REG-009: outbound ABDM sandbox root for the ABHA create/verify adapter.
# Sandbox-only by design: the gate refuses anything but an https "sbx" URL, so
# a mis-typed value fails at import rather than later when the first counter
# request would reach the production ABDM endpoint. Unset means the adapter is
# unavailable and the patient ABHA actions answer 503 (never a fake 200);
# dev.py/test.py leave it unset, and a local sandbox run exports it.
_abdm_sandbox_url = os.getenv("ABDM_SANDBX_BASE_URL", "")
ABDM_SANDBX_BASE_URL = (
    require_sandbox_base_url(_abdm_sandbox_url) if _abdm_sandbox_url else ""
)

# ABD-005: shared secret the ABDM gateway signs Scan and Share callbacks with
# — HMAC-SHA256 over the raw request body, hex digest sent in
# ``X-ABDM-Signature``. There is deliberately **no default**: a published empty
# secret would reduce the check to the presence test the requirement forbids.
# The sandbox issues no shared secret yet, so the callback reads this at request
# time and fails closed when it is empty, except under DEBUG, where a local
# developer has no way to obtain one (dev.py documents that asymmetry).
# test.py supplies a fixed literal so the suite is deterministic.
ABDM_CLIENT_SECRET = os.getenv("ABDM_CLIENT_SECRET", "")

# ABD-007: tolerance for the gateway's callback timestamp, 5 minutes per the
# ABDM specification. A misconfigured window must not silently disable the
# replay check it guards, so a non-numeric or non-positive value falls back to
# the default rather than widening the window.
_abdm_max_skew = os.getenv("ABDM_MAX_SKEW_SECONDS", "")
ABDM_MAX_SKEW_SECONDS = 300
if _abdm_max_skew.isdigit() and int(_abdm_max_skew) > 0:
    ABDM_MAX_SKEW_SECONDS = int(_abdm_max_skew)

# AUD-002: HMAC-SHA256 key the audit hash chain is computed under. There is
# deliberately **no default**: an unkeyed HMAC is just a hash, so anyone who
# can read ``audit.event`` could recompute and forge the chain, and
# tamper-evidence would be a claim rather than a control. A non-DEBUG settings
# import therefore refuses to start without one, mirroring the
# PATIENT_FIELDS_KEY guard above. dev.py and test.py supply deterministic
# values *before* they ``from .base import *`` — a local database must keep
# verifying across restarts, and a random key would make every restart a key
# rotation; production must set AUDIT_HMAC_KEY in the environment.
AUDIT_HMAC_KEY = os.getenv("AUDIT_HMAC_KEY", "")
if not DEBUG and not AUDIT_HMAC_KEY:
    raise ImproperlyConfigured(
        "AUDIT_HMAC_KEY must be set when DEBUG is off: the audit trail is a "
        "tamper-evident HMAC chain (AUD-002) computed under this key, and an "
        "unkeyed chain can be recomputed - and therefore forged - by anyone "
        "who can read the table. dev.py/test.py set a value; production must "
        "export one."
    )

# AUD-004: audit retention window in days, consumed by ``purge_expired``
# (Task 23 schedules the beat entry). The SRS states the requirement —
# "retain audit records per a configurable retention policy" — but names no
# period, and the architecture doc leaves long-term audit retention as an
# open question with the customer (OQ-08), so 365 is a documented
# placeholder, not a compliance claim: it is the value an operator overrides
# per deployment. A non-numeric or non-positive value falls back to the
# default rather than disabling the purge, the same guard
# ABDM_MAX_SKEW_SECONDS uses, so a mis-typed setting cannot silently widen or
# shrink the window.
_audit_retention_days = os.getenv("AUDIT_RETENTION_DAYS", "")
AUDIT_RETENTION_DAYS = 365
if _audit_retention_days.isdigit() and int(_audit_retention_days) > 0:
    AUDIT_RETENTION_DAYS = int(_audit_retention_days)

# PLT-005: file storage for documents and evidence, with access control.
#
# MAX_UPLOAD_MB caps the decoded size of a single upload. The clinical
# artefacts the requirement names - scanned reports, lab result CSVs, the
# occasional photograph - are documents, not media streams, so 10 MB is a
# working default rather than a tuned one. A non-numeric or non-positive value
# falls back to the default instead of disabling the cap, mirroring the
# ABDM_MAX_SKEW_SECONDS guard above: a mistyped setting must not silently
# become "no limit", and must not become zero either, which would refuse
# every upload including an empty one.
_max_upload_mb = os.getenv("MAX_UPLOAD_MB", "")
MAX_UPLOAD_MB = 10
if _max_upload_mb.isdigit() and int(_max_upload_mb) > 0:
    MAX_UPLOAD_MB = int(_max_upload_mb)

# MEDIA_ROOT is where the uploaded bytes live. It is an absolute path so that a
# change of working directory cannot move the storage out from under the rows
# that reference it - the download view resolves ``file_url`` against it, and a
# relative value would make the same row point somewhere else depending on who
# started the process. The default keeps uploads inside the backend directory;
# a deployment is expected to mount a volume and override it.
MEDIA_ROOT = os.getenv("MEDIA_ROOT", str(BASE_DIR / "media"))

# Django caps a request body at 2.5 MB by default (DATA_UPLOAD_MAX_MEMORY_SIZE)
# and raises SuspiciousOperation - surfaced as a 400 - when it is exceeded.
# That ceiling sits *below* the legal upload size above, so without this a
# compliant 10 MB document would be refused before the view, the serializer or
# the allow-list ever ran, and the refusal would have nothing to do with any
# rule the caller can see. It is raised to the cap plus a megabyte of headroom
# for the multipart envelope (field names, boundaries, headers), which the
# file bytes themselves do not count against but the surrounding request does.
#
# FILE_UPLOAD_MAX_MEMORY_SIZE is deliberately left alone: it is the threshold
# at which Django stops buffering an upload in memory and streams it to a
# temporary file, so its 2.5 MB default is the behaviour wanted here - a
# 10 MB document is spooled to disk, not held in RAM.
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024 + 1024 * 1024

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    # SimpleJWT's blacklist app. ROTATE_REFRESH_TOKENS and
    # BLACKLIST_AFTER_ROTATION are already enabled below, but SimpleJWT skips
    # blacklisting (it catches the missing-method AttributeError) while this
    # app is absent — a replayed refresh token would stay valid for its whole
    # lifetime (TEN-006). Its migrations only create new tables.
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_otp",
    # The TOTP plugin carries the device model used for second-factor
    # enrolment (TEN-006). It must be an installed app in its own right; the
    # django_otp entry alone does not bring its migrations or tables along.
    "django_otp.plugins.otp_totp",
    "drf_spectacular",
    "django_celery_beat",
    "apps.identity_tenancy",
    "apps.patient_registry",
    "apps.abdm_gateway",
    "apps.opd",
    "apps.ipd",
    "apps.emergency",
    "apps.icu",
    "apps.ot",
    "apps.lis",
    "apps.ris",
    "apps.pharmacy",
    "apps.blood_bank",
    "apps.billing_insurance",
    "apps.emr",
    "apps.quality_os",
    "apps.audit",
    "apps.integration",
    "apps.platform",
    "apps.realtime",
    "apps.workers",
    "apps.common",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "common.tenant.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATABASES = {
    "default": {
        # common.postgres subclasses the stock PostgreSQL backend so that dotted
        # db_table values ("registry.patient") become real schema qualifiers
        # rather than single identifiers named "registry.patient". See
        # common/postgres.py and architecture doc section 6.
        "ENGINE": os.getenv("DB_ENGINE", "common.postgres"),
        "NAME": os.getenv("PGDATABASE", "mediflow"),
        "USER": os.getenv("PGUSER", "postgres"),
        "PASSWORD": os.getenv("PGPASSWORD", "postgres"),
        "HOST": os.getenv("PGHOST", "localhost"),
        "PORT": os.getenv("PGPORT", "5432"),
        # One transaction per request. TenantMiddleware sets app.tenant_id with
        # set_config(..., is_local=true), which PostgreSQL discards at the end
        # of the enclosing transaction. Without a transaction spanning the
        # request the setting is thrown away by the implicit autocommit
        # transaction before any tenant-owned query runs, so queries execute
        # with no tenant context at all.
        "ATOMIC_REQUESTS": True,
    }
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    }
]

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # Deny by default. Every endpoint must opt in to anonymous access
    # explicitly (see apps/common/urls.py for the health probe). Leaving
    # this unset makes DRF fall back to AllowAny, which would expose every
    # tenant-owned resource to unauthenticated CRUD.
    # TEN-006: the MFA gate is appended after IsAuthenticated, never before
    # it — an anonymous request must fail authentication (401), not be told
    # about an MFA requirement it cannot satisfy. Views that declare their
    # own permission_classes replace this list wholesale; the health probe,
    # the ABDM callback and the TOTP enrolment endpoints do so deliberately.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "common.mfa.MFARequiredIfConfigured",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Binds the tenant from the token's signed claims, overriding the
        # X-Tenant-Id header the middleware resolved. See
        # common/authentication.py for why these are separate steps.
        "common.authentication.TenantBoundJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "300/min",
        # ABDM profile-share callbacks are anonymous by design (the gateway
        # carries no user JWT), so they get their own budget rather than
        # drawing down the shared anonymous bucket. Keyed per HIP ID by
        # AbdmHipThrottle. See architecture doc section 8.4.
        "abdm_callback": "120/min",
    },
}

SPECTACULAR = {
    "TITLE": "Mediflow OS HMIS",
    "VERSION": "0.1.0",
    # Keep the schema and Swagger UI readable while every data endpoint
    # stays authenticated. Without this, requiring authentication would
    # make the API documentation itself unreachable.
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "SERVE_AUTHENTICATION": None,
}

# Token issuance embeds tenant_id, facility_id, role and permissions, so the
# tenant a request acts for comes from a signed credential rather than a
# client-supplied header. See apps/identity_tenancy/tokens.py.
SIMPLE_JWT = {
    "TOKEN_OBTAIN_SERIALIZER": "apps.identity_tenancy.tokens.TenantAwareTokenSerializer",
    # Fail-closed deactivation (TEN-008): the obtain serializer refuses a
    # switched-off membership only at the *next* login, so without a matching
    # refresh-time refusal a live refresh token outruns deactivation — tenant
    # and permission claims survive rotation, and an offboarded user would
    # keep minting fully-claimed access tokens until REFRESH_TOKEN_LIFETIME.
    "TOKEN_REFRESH_SERIALIZER": "apps.identity_tenancy.tokens.TenantAwareTokenRefreshSerializer",
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    # Tenants hold clinical records, so a leaked refresh token should not stay
    # usable for long. Rotation makes a replayed refresh token detectable.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [os.getenv("REDIS_URL", "redis://redis:6379/0")]}},
}

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
# PLT-004/INT-014: beat drives the schedulers through the DatabaseScheduler,
# which seeds these static entries into periodic-task rows on startup, so an
# operator can also add or disable one from the admin without a deploy.
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# PLT-004/INT-014: the scheduled background work. INT-014 is explicit that
# delivery and execution must not depend on Django Channels, which is why these
# live here and not in a consumer.
#
# Every entry points at a zero-argument *dispatcher* in
# ``apps/workers/tasks.py`` rather than at the per-tenant task. A static
# schedule dict is evaluated once, when the settings module is imported, while
# tenants are created at runtime — so a schedule cannot name a tenant, and a
# beat entry that tried to pass a tenant id would be pinned to whichever tenant
# happened to exist at deploy time. Each dispatcher enumerates the tenants and
# enqueues the tenant-scoped task over them, which also puts each tenant's work
# in its own bound session (``platform.notification`` and ``audit.event`` are
# RLS-protected and read nothing at all without one).
#
# The intervals: a daily window for the retention purge (AUD-004, off-peak), an
# hourly cadence matching the ABD-014 failure window, a five-minute sweep of
# due job rows (a job carries its own ``scheduled_at``), and a one-minute sweep
# of undelivered notifications (PLT-001, clinical alerts someone is waiting on).
CELERY_BEAT_SCHEDULE = {
    "purge-expired-audit-events": {
        "task": "apps.workers.tasks.dispatch_audit_retention_purge",
        "schedule": crontab(hour=2, minute=0),
    },
    "scan-abdm-callback-failures": {
        "task": "apps.workers.tasks.dispatch_abdm_callback_failure_scan",
        "schedule": crontab(minute=0),
    },
    "run-due-scheduled-jobs": {
        "task": "apps.workers.tasks.dispatch_due_scheduled_jobs",
        "schedule": crontab(minute="*/5"),
    },
    "dispatch-pending-notifications": {
        "task": "apps.workers.tasks.dispatch_pending_notifications",
        "schedule": crontab(minute="*"),
    },
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
CSRF_TRUSTED_ORIGINS = [
    origin for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if origin
]
