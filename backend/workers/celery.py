"""Celery app and task definitions."""
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
app = Celery("mediflow")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, max_retries=3)
def compute_indicators(self, tenant_id, period_start, period_end):
    """Nightly indicator computation for a tenant."""
    # placeholder - will be implemented with the indicator engine
    pass


@app.task(bind=True, max_retries=3)
def sync_abdm_callback(self, callback_id):
    """Process ABDM callback asynchronously."""
    pass
