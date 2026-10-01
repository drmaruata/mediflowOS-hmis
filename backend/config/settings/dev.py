"""Development settings."""
from .base import *

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("PGDATABASE", "mediflow_dev"),
        "USER": os.getenv("PGUSER", "postgres"),
        "PASSWORD": os.getenv("PGPASSWORD", "postgres"),
        "HOST": os.getenv("PGHOST", "db"),
        "PORT": os.getenv("PGPORT", "5432"),
    }
}
CELERY_TASK_ALWAYS_EAGER = True
