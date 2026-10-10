"""Django project package.

Importing the Celery app here is what makes ``shared_task`` bind to *this*
project's app instead of Celery's anonymous fallback. Without it, every
``task.delay()`` called from a Django process resolves to a default app that
never reads the ``CELERY_*`` settings, so ``CELERY_TASK_ALWAYS_EAGER`` (dev and
test) has no effect and the publish is attempted against the fallback broker
rather than the configured one. This is the documented Celery + Django
integration pattern, and it is what lets tests drive a task through its real
``delay()`` entry point.
"""
from workers.celery import app as celery_app  # noqa: F401
