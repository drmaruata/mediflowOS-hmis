"""Celery application for the mediflow workers.

Only the application lives here. Task definitions belong in
``apps/workers/tasks.py`` as ``@shared_task``, which ``autodiscover_tasks``
picks up because ``apps.workers`` is in ``INSTALLED_APPS``.

This module used to define ``compute_indicators`` and ``sync_abdm_callback`` as
``@app.task`` as well, while ``apps/workers/tasks.py`` defined the same names.
Both registered, under two different module paths, so a caller got whichever
implementation the import path happened to reach: ``workers/urls.py`` pulled in
the ``workers.celery`` copies while everything else imported the
``apps.workers.tasks`` ones. Four task names existed for two tasks, and the
beat schedule could not say which it meant. Keeping one registration point is
the fix, so this module holds the app and nothing else.

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
