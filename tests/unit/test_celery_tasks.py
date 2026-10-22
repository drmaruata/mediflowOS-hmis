"""Celery task wiring, beat schedule and task registry (PLT-004, INT-014).

What this file pins is the *contract* of the background layer, not the engines:

* every per-tenant task runs to an end state under eager execution, and a
  second run is a no-op rather than a second write (AGENTS.md async rule: a
  retried task must not double-write);
* the beat schedule carries exactly the four scheduled entries, at the cadences
  the SRS and Requirement ABD-014 ask for;
* each task name is registered once, from ``apps/workers/tasks.py`` — the
  duplicate definitions that used to sit in ``workers/celery.py`` are gone;
* no task body is a stub. The check parses the source with ``ast`` rather than
  grepping for the word ``pass``, so it cannot be satisfied by a comment or by
  a ``pass`` nested in a branch, and it cannot be fooled by a docstring-only
  body.

The indicator engine and the async ABDM callback re-processor are post-R1.
``run_scheduled_job`` therefore parks a claimed job as ``failed`` with a reason
rather than pretending to compute something — see :class:`TestRunScheduledJob`.

Task 18's ABD-014 alert is here under the brief's produced name:
``task_scan_callback_failures`` is now ``scan_abdm_callback_failures``, so every
task in this module reads the same way. The behaviour is unchanged and
``tests/integration/test_abdm_callback.py`` drives it through the new name.
"""
import ast
import pathlib
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.identity_tenancy.models import Tenant
from apps.platform.models import Notification, ScheduledJob
from apps.workers import tasks as worker_tasks
from workers.celery import app as celery_app

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

BACKEND = pathlib.Path(__file__).resolve().parent.parent.parent / "backend"

#: The four per-tenant tasks the beat dispatchers fan out over. Every one takes
#: an explicit tenant argument, which is what AGENTS.md §4 requires: a task must
#: never run without tenant context.
PER_TENANT_TASKS = (
    worker_tasks.dispatch_notification,
    worker_tasks.purge_expired_audit_events,
    worker_tasks.run_scheduled_job,
    worker_tasks.scan_abdm_callback_failures,
)

#: The four zero-argument dispatchers the static beat schedule points at. A
#: static ``CELERY_BEAT_SCHEDULE`` is frozen at import time and so cannot carry
#: tenant ids, which are created at runtime — hence a task that enumerates the
#: tenants and enqueues the per-tenant work.
DISPATCHERS = (
    worker_tasks.dispatch_audit_retention_purge,
    worker_tasks.dispatch_abdm_callback_failure_scan,
    worker_tasks.dispatch_due_scheduled_jobs,
    worker_tasks.dispatch_pending_notifications,
)


def _make_tenant(slug):
    """A tenant row. ``identity.tenant`` is the one table with no ``tenant_id``
    and no RLS policy, so no session binding is needed to write it."""
    return Tenant.objects.create(name=slug, slug=slug)


def _stubbed_functions(path):
    """Names of functions in ``path`` whose body cannot do anything.

    A docstring alone, ``pass`` and ``...`` all leave a function with nothing
    to run, which is exactly how the three placeholder tasks looked
    implemented while doing nothing. The walk is over the AST, so a ``pass``
    nested inside a branch or an ``except`` block is not mistaken for a stub,
    and a function that does real work *and* contains a ``pass`` passes.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    stubs = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            # A leading string documents the function; it does not implement it.
            body = body[1:]
        if not body:
            stubs.append(node.name)
        elif len(body) == 1 and (
            isinstance(body[0], ast.Pass)
            or (
                isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and body[0].value.value is Ellipsis
            )
        ):
            stubs.append(node.name)
    return stubs


class TestNoPlaceholderBodyRemains:
    """No task may exist as a body that does nothing.

    These are the tests Task 23 was written against first: the three ``pass``
    bodies (``compute_indicators``, ``sync_abdm_callback``,
    ``send_notification``) were the state of the world, so this fails until the
    bodies are either implemented or removed.
    """

    def test_tasks_module_defines_no_stub_functions(self):
        assert _stubbed_functions(BACKEND / "apps" / "workers" / "tasks.py") == []

    def test_celery_app_module_defines_no_stub_functions(self):
        assert _stubbed_functions(BACKEND / "workers" / "celery.py") == []

    def test_the_deleted_placeholders_are_not_importable_from_either_module(self):
        """The duplicate registration is the bug: one task name, two bodies.

        ``workers/celery.py`` used to define ``compute_indicators`` and
        ``sync_abdm_callback`` as ``@app.task`` while ``apps/workers/tasks.py``
        defined the same names as ``@shared_task``. Both registered, under
        different module paths, so which implementation a caller got depended
        purely on which module it imported from.
        """
        import workers.celery as celery_app_module

        for name in ("compute_indicators", "sync_abdm_callback", "send_notification"):
            assert not hasattr(celery_app_module, name), (
                f"{name} is still defined on the Celery app module; a task body "
                "belongs in apps/workers/tasks.py as a @shared_task"
            )

    def test_the_unrouted_placeholder_caller_is_removed(self):
        """``workers/urls.py`` was the only caller of the placeholder.

        It was never mounted in ``config/urls.py``, so it imported a task body
        that nothing could reach — dead code holding a reference to a task that
        was being deleted. Leaving it would have left an import of a name that
        no longer exists, waiting for the first ``include("workers.urls")``.
        """
        assert not (BACKEND / "workers" / "urls.py").exists()


class TestTaskRegistrationIsCanonical:
    """Each task name registers exactly once, from one module."""

    def test_worker_tasks_register_from_the_tasks_module_only(self):
        # autodiscover_tasks registers a lazy fixup; importing the default
        # modules is what a worker does on start-up, so it is what exercises
        # the registration path under test.
        celery_app.loader.import_default_modules()
        registered = {
            name for name in celery_app.tasks if name.startswith("apps.workers.tasks.")
        }
        assert registered == {
            "apps.workers.tasks.dispatch_notification",
            "apps.workers.tasks.purge_expired_audit_events",
            "apps.workers.tasks.run_scheduled_job",
            "apps.workers.tasks.scan_abdm_callback_failures",
            "apps.workers.tasks.dispatch_audit_retention_purge",
            "apps.workers.tasks.dispatch_abdm_callback_failure_scan",
            "apps.workers.tasks.dispatch_due_scheduled_jobs",
            "apps.workers.tasks.dispatch_pending_notifications",
        }

    def test_no_task_registers_from_the_app_module(self):
        celery_app.loader.import_default_modules()
        assert not [name for name in celery_app.tasks if name.startswith("workers.celery.")]

    def test_every_registered_task_resolves_to_the_tasks_module(self):
        """A name registered twice could only be caught here.

        ``app.tasks`` is a dict, so a duplicate name collapses silently; pinning
        that each name's implementation lives in ``apps.workers.tasks`` is what
        proves the collapsing never had anything to collapse.
        """
        celery_app.loader.import_default_modules()
        for name in celery_app.tasks:
            if name.startswith("apps.workers.tasks."):
                assert celery_app.tasks[name].__module__ == "apps.workers.tasks"


class TestRetryPolicy:
    """PLT-004 asks for retry and back-off, not just a task that runs once."""

    @pytest.mark.parametrize(
        "task", PER_TENANT_TASKS + DISPATCHERS, ids=lambda task: task.name
    )
    def test_policy_is_declared_on_every_task(self, task):
        assert task.autoretry_for == (Exception,)
        assert task.max_retries == 5
        assert task.retry_backoff is True
        assert task.retry_backoff_max == 600


class TestBeatSchedule:
    """Four scheduled entries, at the cadences they are pinned to."""

    def test_exactly_the_four_documented_entries_exist(self):
        assert set(settings.CELERY_BEAT_SCHEDULE) == {
            "purge-expired-audit-events",
            "scan-abdm-callback-failures",
            "run-due-scheduled-jobs",
            "dispatch-pending-notifications",
        }

    def test_every_entry_points_at_a_dispatcher(self):
        dispatchers = {task.name for task in DISPATCHERS}
        for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
            assert entry["task"] in dispatchers, name

    def test_the_nightly_purge_runs_at_two_in_the_morning(self):
        """AUD-004's retention purge is scheduled at 02:00, off-peak. The
        crontab's own expansion is asserted, not the arguments used to build
        it, so a rewritten entry cannot quietly drift to a different hour."""
        schedule = settings.CELERY_BEAT_SCHEDULE["purge-expired-audit-events"]["schedule"]
        assert schedule.hour == {2}
        assert schedule.minute == {0}

    def test_the_callback_failure_scan_is_hourly(self):
        """ABD-014 counts a one-hour window, so the scan has to run at least
        hourly or it would report a burst an hour late."""
        schedule = settings.CELERY_BEAT_SCHEDULE["scan-abdm-callback-failures"]["schedule"]
        assert schedule.hour == set(range(24))
        assert schedule.minute == {0}

    def test_the_due_job_sweep_runs_every_five_minutes(self):
        """A job row carries its own ``scheduled_at``; the sweep only has to be
        frequent enough that a due job is picked up promptly. Five minutes
        bounds a due job's delay without hammering the broker once a minute."""
        minute = settings.CELERY_BEAT_SCHEDULE["run-due-scheduled-jobs"]["schedule"].minute
        assert minute == set(range(0, 60, 5))

    def test_the_notification_sweep_runs_every_minute(self):
        """PLT-001: an alert a provider waits on is not a minute's delay."""
        minute = settings.CELERY_BEAT_SCHEDULE["dispatch-pending-notifications"][
            "schedule"
        ].minute
        assert minute == set(range(60))


class TestDispatchNotification:
    """PLT-001 / INT-012: a persisted notification reaches its tenant's sockets."""

    def test_a_pending_notification_is_pushed_to_its_own_tenant(self, monkeypatch):
        pushed = []
        monkeypatch.setattr(
            "apps.platform.views._push_notification",
            lambda tenant_id, payload: pushed.append((tenant_id, payload)),
        )
        tenant = _make_tenant("dispatch-hospital")
        notification = Notification.objects.create(
            tenant_id=tenant.id,
            user_id=uuid.uuid4(),
            title="Result ready",
            body="Your report is available.",
            type="info",
            persisted=True,
            delivered=False,
        )

        worker_tasks.dispatch_notification.delay(str(notification.id), str(tenant.id))

        assert len(pushed) == 1
        tenant_id, payload = pushed[0]
        assert tenant_id == str(tenant.id)
        assert payload["id"] == str(notification.id)

    def test_delivered_stays_the_consumers_flag(self):
        """The task must not flip ``delivered``.

        If it did, a row would read as delivered by a task that only published
        a message: with no socket connected the frame goes nowhere and the flag
        would be a lie. The consumer sets it when a socket actually receives
        the row (T22); a row nobody listened to stays ``delivered=False``,
        which is the honest state and the one that gets it re-enqueued.
        """
        tenant = _make_tenant("no-flip-hospital")
        notification = Notification.objects.create(
            tenant_id=tenant.id,
            user_id=uuid.uuid4(),
            title="Result ready",
            body="Your report is available.",
            type="info",
            persisted=True,
            delivered=False,
        )
        monkeypatch_layer = []

        worker_tasks.dispatch_notification.delay(str(notification.id), str(tenant.id))

        notification.refresh_from_db()
        assert notification.delivered is False
        assert monkeypatch_layer == []

    def test_a_missing_row_is_a_no_op_that_never_raises(self):
        """Idempotency: a retried dispatch must not crash on a row that is gone.

        A deleted row means the notification was withdrawn, so the task logs
        the id and returns. Raising would start an autoretry loop against a
        condition retrying cannot fix.
        """
        result = worker_tasks.dispatch_notification.delay(uuid.uuid4(), uuid.uuid4()).result

        assert result["pushed"] is False
        assert result["reason"] == "no such notification row"

    def test_an_already_delivered_row_is_not_pushed_again(self, monkeypatch):
        """A second run must not re-open a notification the user already saw."""
        pushed = []
        monkeypatch.setattr(
            "apps.platform.views._push_notification",
            lambda tenant_id, payload: pushed.append((tenant_id, payload)),
        )
        tenant = _make_tenant("already-hospital")
        notification = Notification.objects.create(
            tenant_id=tenant.id,
            user_id=uuid.uuid4(),
            title="Result ready",
            body="Your report is available.",
            type="info",
            persisted=True,
            delivered=True,
        )

        worker_tasks.dispatch_notification.delay(str(notification.id), str(tenant.id))

        assert pushed == []

    def test_a_note_from_another_tenant_matches_nothing(self, monkeypatch):
        """A fabricated id is scoped by tenant, so it cannot push another
        hospital's notification — the row lookup names both ids, exactly as
        the consumer's ``_mark_delivered`` does."""
        pushed = []
        monkeypatch.setattr(
            "apps.platform.views._push_notification",
            lambda tenant_id, payload: pushed.append((tenant_id, payload)),
        )
        owner = _make_tenant("owner-hospital")
        stranger = _make_tenant("stranger-hospital")
        notification = Notification.objects.create(
            tenant_id=owner.id,
            user_id=uuid.uuid4(),
            title="Result ready",
            body="Your report is available.",
            type="info",
            persisted=True,
            delivered=False,
        )

        worker_tasks.dispatch_notification.delay(str(notification.id), str(stranger.id))

        assert pushed == []


class TestPurgeExpiredAuditEvents:
    """AUD-004's retention purge, as a scheduled task."""

    def test_the_task_deletes_only_past_retention_rows(self):
        tenant = _make_tenant("purge-hospital")
        stale = AuditEvent.objects.create(
            tenant_id=tenant.id, action="read", entity_type="registry.patient",
            entity_id="AUD-stale",
        )
        fresh = AuditEvent.objects.create(
            tenant_id=tenant.id, action="read", entity_type="registry.patient",
            entity_id="AUD-fresh",
        )
        AuditEvent.objects.filter(pk=stale.pk).update(
            occurred_at=timezone.now() - timedelta(days=900)
        )

        result = worker_tasks.purge_expired_audit_events.delay(str(tenant.id)).result

        assert result["deleted"] == 1
        assert not AuditEvent.objects.filter(pk=stale.pk).exists()
        assert AuditEvent.objects.filter(pk=fresh.pk).exists()

    def test_running_it_twice_deletes_the_same_set(self):
        """The retry idempotency pin.

        Deletion is naturally idempotent — the second run finds nothing left
        inside the window — but the task holds an open transaction, and a task
        that leaked a savepoint or re-counted already-deleted rows would show
        up here as a second ``deleted`` figure or as surviving rows coming back.
        """
        tenant = _make_tenant("purge-twice-hospital")
        for index in range(3):
            row = AuditEvent.objects.create(
                tenant_id=tenant.id, action="read", entity_type="registry.patient",
                entity_id=f"AUD-{index}",
            )
            AuditEvent.objects.filter(pk=row.pk).update(
                occurred_at=timezone.now() - timedelta(days=900)
            )

        first = worker_tasks.purge_expired_audit_events.delay(str(tenant.id)).result
        survivors = set(AuditEvent.objects.values_list("entity_id", flat=True))
        second = worker_tasks.purge_expired_audit_events.delay(str(tenant.id)).result
        survivors_after = set(AuditEvent.objects.values_list("entity_id", flat=True))

        assert first["deleted"] == 3
        assert second["deleted"] == 0
        assert survivors == set()
        assert survivors_after == set()

    def test_another_tenants_rows_are_never_deleted(self):
        """One tenant's retention policy is not another's evidence."""
        mine = _make_tenant("purge-mine")
        theirs = _make_tenant("purge-theirs")
        row = AuditEvent.objects.create(
            tenant_id=theirs.id, action="read", entity_type="registry.patient",
            entity_id="AUD-foreign",
        )
        AuditEvent.objects.filter(pk=row.pk).update(
            occurred_at=timezone.now() - timedelta(days=900)
        )

        worker_tasks.purge_expired_audit_events.delay(str(mine.id))

        assert AuditEvent.objects.filter(pk=row.pk).exists()


class TestScanCallbackFailureRename:
    """ABD-014: the Task 18 alert, under the name the brief pins."""

    def test_the_task_is_importable_under_the_new_name(self):
        assert worker_tasks.scan_abdm_callback_failures.name == (
            "apps.workers.tasks.scan_abdm_callback_failures"
        )

    def test_the_old_name_is_gone(self):
        """A rename that leaves the old name importable leaves two names for one
        task, which is the duplicate-registration problem in a new shape."""
        assert not hasattr(worker_tasks, "task_scan_callback_failures")


class TestDispatchers:
    """Beat points at zero-argument dispatchers, because it cannot carry tenants."""

    def test_two_active_tenants_each_get_their_own_task(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            worker_tasks, "purge_expired_audit_events", type(
                "Recorder", (), {"delay": staticmethod(lambda tenant_id: seen.append(tenant_id))}
            )(),
        )
        first = _make_tenant("fan-out-a")
        second = _make_tenant("fan-out-b")

        result = worker_tasks.dispatch_audit_retention_purge.delay().result

        assert sorted(seen) == sorted([str(first.id), str(second.id)])
        assert result["tenants"] == 2
        assert result["enqueued"] == 2

    def test_a_deployment_with_no_tenants_enqueues_nothing(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            worker_tasks, "purge_expired_audit_events", type(
                "Recorder", (), {"delay": staticmethod(lambda tenant_id: seen.append(tenant_id))}
            )(),
        )
        Tenant.objects.all().delete()

        result = worker_tasks.dispatch_audit_retention_purge.delay().result

        assert seen == []
        assert result["tenants"] == 0
        assert result["enqueued"] == 0

    def test_every_dispatcher_returns_counts_not_identifiers(self, monkeypatch):
        """PLT-004 asks for visibility. A task result lives in a backend that
        sits outside the hospital's boundary, so it carries counts and ids only
        — never a notification body, an audit entity id or a job payload."""
        monkeypatch.setattr(
            worker_tasks, "run_scheduled_job", type(
                "Recorder", (), {"delay": staticmethod(lambda job_id: None)}
            )(),
        )
        _make_tenant("reporting-hospital")

        for dispatcher in (
            worker_tasks.dispatch_audit_retention_purge,
            worker_tasks.dispatch_abdm_callback_failure_scan,
            worker_tasks.dispatch_due_scheduled_jobs,
            worker_tasks.dispatch_pending_notifications,
        ):
            result = dispatcher.delay().result
            assert isinstance(result, dict)
            assert set(result) == {"schedule", "tenants", "enqueued", "truncated"}


class TestScheduledJobClaim:
    """A claimed job runs once, whatever the scheduler does."""

    def setup_method(self):
        self.tenant = _make_tenant("job-hospital")

    def _job(self, **kwargs):
        defaults = {
            "tenant_id": self.tenant.id,
            "job_type": "report_generation",
            "status": "pending",
            "scheduled_at": timezone.now() - timedelta(minutes=1),
        }
        defaults.update(kwargs)
        return ScheduledJob.objects.create(**defaults)

    def test_a_due_job_reaches_a_terminal_state(self):
        job = self._job()

        result = worker_tasks.run_scheduled_job.delay(str(job.id)).result

        job.refresh_from_db()
        assert job.status == "failed"
        assert job.started_at is not None
        assert job.completed_at is not None
        assert result["status"] == "failed"
        assert result["job_type"] == "report_generation"
        assert result["tenant_id"] == str(self.tenant.id)
        assert "no R1 implementation" in job.result["reason"]
        assert job.result == {
            "reason": "report_generation has no R1 implementation — engine deferred"
        }

    def test_running_it_twice_executes_once(self):
        """The claim UPDATE is the idempotency pin.

        ``UPDATE ... WHERE id = %s AND status = 'pending'`` returns a rowcount,
        and a row already claimed updates nothing. So a scheduler that fires
        twice, or a worker that replays the message, leaves exactly one
        ``started_at`` and one result: the second run is a no-op, not a second
        write of the same terminal state.
        """
        job = self._job()

        worker_tasks.run_scheduled_job.delay(str(job.id))
        first_started = ScheduledJob.objects.get(pk=job.pk).started_at
        second = worker_tasks.run_scheduled_job.delay(str(job.id)).result
        second_started = ScheduledJob.objects.get(pk=job.pk).started_at

        assert first_started == second_started
        assert second["ran"] is False
        assert second["status"] == "failed"
        assert ScheduledJob.objects.filter(
            pk=job.pk, started_at=first_started, status="failed"
        ).exists()

    def test_a_row_that_is_not_pending_is_left_alone(self):
        job = self._job(status="completed", completed_at=timezone.now())

        worker_tasks.run_scheduled_job.delay(str(job.id))

        job.refresh_from_db()
        assert job.status == "completed"
        assert job.started_at is None

    def test_a_row_from_another_tenant_is_not_runnable_by_id_alone(self):
        """The row is the tenant authority, and it is resolved first.

        ``platform.scheduled_job`` carries no RLS policy (migration 0004
        freezes only ``platform.notification`` and ``platform.feature_flag``),
        so application scoping is the only control here: the claim and the
        terminal write are both filtered by the row's own tenant, and the
        tenant is bound from the row before either runs. The task's own return
        value names the tenant it ran under, so a mis-bound run is visible in
        the result rather than only in the database.
        """
        other = _make_tenant("other-tenant-hospital")
        job = ScheduledJob.objects.create(
            tenant_id=other.id,
            job_type="report_generation",
            status="pending",
            scheduled_at=timezone.now() - timedelta(minutes=1),
        )

        result = worker_tasks.run_scheduled_job.delay(str(job.id)).result

        job.refresh_from_db()
        assert job.started_at is not None
        assert result["tenant_id"] == str(other.id)
        assert result["job_type"] == "report_generation"

    def test_a_missing_job_is_a_no_op_that_never_raises(self):
        result = worker_tasks.run_scheduled_job.delay(uuid.uuid4()).result

        assert result["ran"] is False
        assert result["status"] == "missing"
