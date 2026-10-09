"""Development settings."""
import os

# REG-008: a deterministic dev passphrase so a local database keeps decrypting
# across restarts (a random value would make every restart a key rotation).
# setdefault keeps a developer's own PATIENT_FIELDS_KEY when one is exported.
# Set before importing base, whose non-DEBUG guard needs a value; DEBUG=True
# below is the escape hatch when no key at all is wanted.
os.environ.setdefault(
    "PATIENT_FIELDS_KEY", "mediflow-dev-patient-fields-key-reg-008"
)

from .base import *  # noqa: E402,F401,F403

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
