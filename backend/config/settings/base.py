"""Shared Django settings."""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "false") == "true"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

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
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
CSRF_TRUSTED_ORIGINS = [
    origin for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if origin
]
