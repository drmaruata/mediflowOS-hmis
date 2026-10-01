"""Development settings."""
from .base import *

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True
DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "common.postgres"),
        "NAME": os.getenv("PGDATABASE", "mediflow_dev"),
        "USER": os.getenv("PGUSER", "postgres"),
        "PASSWORD": os.getenv("PGPASSWORD", "postgres"),
        # Container-local hostname by default, matching the docker compose
        # service name. Override with PGHOST=localhost when running against a
        # database installed directly on the host.
        "HOST": os.getenv("PGHOST", "db"),
        "PORT": os.getenv("PGPORT", "5432"),
        "ATOMIC_REQUESTS": True,
    }
}
CELERY_TASK_ALWAYS_EAGER = True
