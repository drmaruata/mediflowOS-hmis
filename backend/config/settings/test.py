"""Settings for fast, isolated backend tests."""
from .base import *

DEBUG = False
SECRET_KEY = "test-only-secret-key"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
MIDDLEWARE = [
    middleware
    for middleware in MIDDLEWARE
    if middleware != "common.tenant.TenantMiddleware"
]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}
CELERY_TASK_ALWAYS_EAGER = True