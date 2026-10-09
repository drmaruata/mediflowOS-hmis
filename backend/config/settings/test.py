"""Settings for fast, isolated backend tests."""
from .base import *

DEBUG = False
SECRET_KEY = "test-only-secret-key"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        # SQLite defaults to BEGIN DEFERRED, where a read-then-write
        # transaction upgrades SHARED -> RESERVED. When two connections both
        # read before either writes (exactly what the sequence-service
        # concurrency tests arrange), the upgrade deadlocks: each fails
        # immediately with "database is locked", the busy timeout never
        # applies, and neither transaction can win. BEGIN IMMEDIATE takes the
        # write lock at transaction start, serialising writers so the loser
        # waits for the winner's commit and then reads its row.
        "OPTIONS": {"transaction_mode": "IMMEDIATE"},
        # Production wraps each request in a transaction (base.py) so the tenant
        # session setting stays scoped for the whole request. The fast suite
        # drives views through the test client without database access, which
        # ATOMIC_REQUESTS would break, since it opens a connection for every
        # request regardless of whether the view needs one. The transaction
        # coupling is covered directly in tests/unit/test_tenant_middleware.py,
        # and the production value is asserted in test_project_settings.py.
        "ATOMIC_REQUESTS": False,
    }
}
# TenantMiddleware is kept in the stack. Its session-setting calls are guarded
# on the database vendor, so they no-op on SQLite while the request/transaction
# behaviour around them still runs under test.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}
CELERY_TASK_ALWAYS_EAGER = True