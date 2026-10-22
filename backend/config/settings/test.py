"""Settings for fast, isolated backend tests."""
import atexit
import os
import shutil
import tempfile

# REG-008: a *fixed literal* so the crypto-coupling integration tests
# (test_patient_encryption.py derives its AES/HMAC keys from exactly this string)
# stay deterministic regardless of host environment. Set before importing base,
# whose non-DEBUG guard would otherwise refuse to start.
os.environ["PATIENT_FIELDS_KEY"] = "kepi-12-unit-passphrase"

# ABD-005: the shared secret the callback verifies its HMAC against, set before
# importing base so the deterministic value reaches the settings object and the
# fail-closed path for an unset secret is only taken by a test that overrides it
# on purpose. Any value works — this one keeps the suite host-independent.
os.environ.setdefault("ABDM_CLIENT_SECRET", "kepi-15-unit-passphrase")

# AUD-002: the HMAC key the audit hash chain is computed under. Fixed so a chain
# written by one test verifies in another, and so base's non-DEBUG guard (an
# unverifiable chain must not start) is satisfied without exporting anything.
os.environ.setdefault("AUDIT_HMAC_KEY", "kepi-21-unit-passphrase")

from .base import *  # noqa: E402,F401,F403

DEBUG = False
SECRET_KEY = "test-only-secret-key"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        # SQLite defaults to BEGIN DEFERRED, where a read-then-write transaction
        # upgrades SHARED -> RESERVED. When two connections both read before
        # either writes (what the sequence-service concurrency tests arrange), the
        # upgrade deadlocks: each fails immediately with "database is locked" and
        # the busy timeout never applies. BEGIN IMMEDIATE takes the write lock at
        # transaction start, serialising writers so the loser waits and then reads.
        "OPTIONS": {"transaction_mode": "IMMEDIATE"},
        # Production wraps each request in a transaction (base.py) so the tenant
        # session setting stays scoped for the whole request. The fast suite
        # drives views without database access, which ATOMIC_REQUESTS would break
        # by opening a connection for every request regardless. The transaction
        # coupling is covered in test_tenant_middleware.py and the production
        # value asserted in test_project_settings.py.
        "ATOMIC_REQUESTS": False,
    }
}
# TenantMiddleware stays in the stack: its session-setting calls are guarded on
# the database vendor, so they no-op on SQLite while the request/transaction
# behaviour around them still runs under test.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}
CELERY_TASK_ALWAYS_EAGER = True

# PLT-005: uploads go to a scratch directory *outside* the repository tree.
# base.py defaults MEDIA_ROOT to backend/media, which would leave every
# test-written document in the working tree - a git status that is never clean
# and a document staged for commit by accident. A unique directory per run also
# keeps concurrent pytest processes apart, which matters because the path shape
# is asserted to the byte in test_platform_files.py.
#
# The cap is 1 MB so the oversize test writes just over a megabyte rather than
# ten: the rule under test is "over the cap is refused", not "ten megabytes is
# slow". The suite reads MAX_UPLOAD_MB rather than hardcoding either value.
MAX_UPLOAD_MB = 1
# Recomputed rather than inherited: base.py derived this from the *base* 10 MB
# cap, so the two would silently disagree once the cap above is lowered, and an
# upload between 1 MB and 11 MB would be refused by Django before the view ran -
# a 400 naming no cap of this project's own. The oversize test depends on the
# ceiling staying above the cap plus the multipart envelope.
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024 + 1024 * 1024
MEDIA_ROOT = tempfile.mkdtemp(prefix="mediflow-test-media-")
atexit.register(shutil.rmtree, MEDIA_ROOT, ignore_errors=True)
