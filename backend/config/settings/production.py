"""Production settings.

Architecture doc section 11 requires TLS, secrets from a manager rather than the
repository, and no debug output. Section 15 adds HSTS behind a proxy.

The most important change from the previous version is that it fails at startup
rather than running with a published key. ``base.py`` still defaults
``SECRET_KEY`` to the literal string "change-me" for local development; that
value must never reach production, because it signs every JWT this system issues
and is published in this repository.
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEBUG = False

# --- fail fast on a missing secret -------------------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set in production. The base.py default is "
        "'change-me', which is published in this repository and would let anyone "
        "forge access tokens."
    )
# SimpleJWT signs with HMAC-SHA256, which needs at least 32 bytes of key. A short
# key still "works" but is brute-forceable, so it is rejected rather than warned
# about - PyJWT only emits an InsecureKeyLengthWarning at runtime.
if len(SECRET_KEY.encode()) < 32:
    raise ImproperlyConfigured(
        f"DJANGO_SECRET_KEY must be at least 32 bytes for HMAC-SHA256 token "
        f"signing; got {len(SECRET_KEY.encode())}. Generate one with "
        "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
    )

# --- hosts -------------------------------------------------------------------
# "*" in base.py is a wildcard. In production an explicit allow-list is required,
# because ALLOWED_HOSTS is what stops Host-header cache poisoning.
ALLOWED_HOSTS = [
    host
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host
]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must list the public hostnames in production. "
        "An empty list falls back to base.py's '*' wildcard."
    )

# --- transport security ------------------------------------------------------
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
# Same-site Lax still sends the cookie on top-level navigations, which is what a
# normal sign-in redirect needs, while blocking cross-site POSTs.
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# HSTS. Only safe because the deployment terminates TLS; enabling it over plain
# HTTP would lock browsers out of the site for the max-age window.
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Behind a TLS-terminating proxy or load balancer, so Django can tell the request
# arrived over HTTPS. Without this every request looks like plain HTTP and the
# secure-cookie flags above would never be satisfied in practice.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

X_FRAME_OPTIONS = "DENY"

# --- CORS --------------------------------------------------------------------
# base.py leaves this unset. The architecture doc requires origins to be
# restricted rather than wildcarded.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    origin
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin
]
if not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured(
        "CORS_ALLOWED_ORIGINS must list the frontend origins in production. "
        "base.py does not set CORS_ALLOW_ALL_ORIGINS, so an empty list means "
        "no cross-origin request is permitted at all."
    )
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

# --- static files ------------------------------------------------------------
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # ManifestStaticFilesStorage requires collectstatic to have run, and
        # fails loudly on a missing file rather than 404ing in production.
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}

# --- database ----------------------------------------------------------------
CONN_MAX_AGE = int(os.getenv("PG_CONN_MAX_AGE", "60"))
CONN_HEALTH_CHECKS = True

# --- logging -----------------------------------------------------------------
# Audit and error reporting are not optional for a clinical system holding PHI
# (architecture doc section 11 and section 16). Django's default logging sends
# everything to console at WARNING with no structure at all.
#
# Note: a structured JSON formatter would need python-json-logger, which is not
# declared. Until it is, these are plain console lines. Moving to JSON logging
# is a small change and is worth doing before the log pipeline is wired up in
# section 16, since dashboards key on structured fields.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    "loggers": {
        # django.request logs every 4xx at WARNING, which is noisy for a scanner
        # probing the API; 5xx still surfaces at ERROR.
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}