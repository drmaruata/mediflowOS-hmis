"""Celery application for the mediflow workers.

Only the application lives here. Task definitions belong in
``apps/workers/tasks.py`` as ``@shared_task``, which ``autodiscover_tasks``
picks up because ``apps.workers`` is in ``INSTALLED_APPS``. This module used to
define the same task names as ``@app.task`` as well, so both registered under
two module paths and a caller got whichever the import path reached: four task
names for two tasks, and a beat schedule that could not say which it meant.

``DJANGO_SETTINGS_MODULE`` is defaulted here rather than in ``manage.py``
because a Celery worker imports this module directly, without going through
Django's own entry point.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

app = Celery("mediflow")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
