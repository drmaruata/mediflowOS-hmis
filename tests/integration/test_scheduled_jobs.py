"""Scheduled background work end to end: beat dispatcher to task to effect.

The unit suite pins each task's own contract. This one drives the path the
deployment actually runs: a ``CELERY_BEAT_SCHEDULE`` entry fires a zero-argument
dispatcher, the dispatcher enumerates the tenants and enqueues the per-tenant
task, and the task's effect lands in the database. Everything runs through the
real ``delay()`` entry point under ``CELERY_TASK_ALWAYS_EAGER``, so a defect in
the wiring — a dispatcher that skips a tenant, a job that runs twice, a claim
that two workers race — is visible here rather than only in production.

The WebSocket half of the notification sweep matters more than it looks: the
consumer that flips ``delivered`` runs in a different process from the task that
pushes, so the round trip through the real channel layer is what proves the T22
push/flip split survives being driven by a job instead of by a request.
"""
import uuid
from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.identity_tenancy.models import Role, Tenant, UserMembership
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.platform.models import Notification, ScheduledJob
from apps.workers import tasks as worker_tasks
from config.asgi import application

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

NOTIFICATIONS_WS = "/ws/notifications/"


def _run(scenario):
    """Drive one coroutine to completion from a sync test.

    ``async_to_sync`` runs the coroutine on its own event loop in its own
    thread, and the consumer's task and its channel-layer queues are bound to
    that loop — so a sweep that has to reach a socket has to happen inside a
    single ``scenario`` rather than across several ``_run`` calls.
    """
    return async_to_sync(scenario)()


def _make_tenant(name):
    return Tenant.objects.create(name=name, slug=f"sched-{uuid.uuid4().hex[:8]}")


def _make_user(tenant, username):
    user = get_user_model().objects.create_user(
        username=username, password="sched-test-pass"
    )
    role = Role.objects.create(tenant=tenant, name=f"role-{username}", permissions=[])
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    return user


def _access_token(user):
    """A signed access token minted by the production issuer (TEN-006)."""
    return str(TenantAwareTokenSerializer.get_token(user).access_token)


def _job(tenant, *, minutes_ago, job_type="report_generation", status="pending"):
    return ScheduledJob.objects.create(
        tenant_id=tenant.id,
        job_type=job_type,
        status=status,
        scheduled_at=timezone.now() - timedelta(minutes=minutes_ago),
    )


class TestScheduledJobSweep:
    """The ``run-due-scheduled-jobs`` beat entry, from entry to terminal state."""

    def test_a_due_job_is_claimed_run_and_parked(self):
        tenant = _make_tenant("Due Job Hospital")
        job = _job(tenant, minutes_ago=5)

        worker_tasks.dispatch_due_scheduled_jobs.delay()

        job.refresh_from_db()
        assert job.status == "failed"
        assert job.started_at is not None
        assert job.completed_at is not None
        # Honest terminal state: R1 ships no indicator engine and no async
        # callback re-processor, so a parked job says so rather than sitting
        # "running" forever with no result to show.
        assert job.result == {
            "reason": "report_generation has no R1 implementation — engine deferred"
        }

    def test_a_pending_future_job_is_not_picked_up(self):
        """``scheduled_at`` is the only clock; picking up a future job would run
        work before its time and burn a retry on a job nobody asked for yet."""
        tenant = _make_tenant("Future Job Hospital")
        job = ScheduledJob.objects.create(
            tenant_id=tenant.id,
            job_type="report_generation",
            status="pending",
            scheduled_at=timezone.now() + timedelta(hours=6),
        )

        worker_tasks.dispatch_due_scheduled_jobs.delay()

        job.refresh_from_db()
        assert job.status == "pending"
        assert job.started_at is None

    def test_the_sweep_twice_runs_the_job_once(self):
        """The re-entrancy guard, across the dispatcher boundary too.

        A dispatcher that re-enqueued an already-claimed row would restart the
        job from scratch; the claim UPDATE inside the task is what finally
        stops it, so the sweep being run twice has to leave exactly one
        ``started_at`` stamp and one result write.
        """
        tenant = _make_tenant("Swept Twice Hospital")
        job = _job(tenant, minutes_ago=5)

        worker_tasks.dispatch_due_scheduled_jobs.delay()
        first_started = ScheduledJob.objects.get(pk=job.pk).started_at
        worker_tasks.dispatch_due_scheduled_jobs.delay()
        second_started = ScheduledJob.objects.get(pk=job.pk).started_at

        assert first_started is not None
        assert first_started == second_started
        assert ScheduledJob.objects.filter(pk=job.pk).count() == 1

    def test_each_tenants_job_runs_under_its_own_tenant(self):
        """The dispatcher fans out per tenant; a job is never run inside another
        hospital's session."""
        first = _make_tenant("Two Tenant Hospital A")
        second = _make_tenant("Two Tenant Hospital B")
        job_a = _job(first, minutes_ago=5)
        job_b = _job(second, minutes_ago=5)

        worker_tasks.dispatch_due_scheduled_jobs.delay()

        job_a.refresh_from_db()
        job_b.refresh_from_db()
        assert job_a.result["reason"].startswith("report_generation")
        assert job_b.result["reason"].startswith("report_generation")
        assert job_a.status == job_b.status == "failed"
        assert job_a.tenant_id == first.id
        assert job_b.tenant_id == second.id

    def test_a_job_already_terminal_is_left_alone(self):
        tenant = _make_tenant("Terminal Job Hospital")
        job = _job(tenant, minutes_ago=5, status="completed")

        worker_tasks.dispatch_due_scheduled_jobs.delay()

        job.refresh_from_db()
        assert job.status == "completed"
        assert job.started_at is None
        assert job.result is None

    def test_a_job_from_a_tenant_with_no_other_rows_still_runs(self):
        """Enumeration is over tenants, not over rows: a hospital with exactly
        one scheduled job and nothing else is still swept."""
        tenant = _make_tenant("Lonely Job Hospital")
        job = _job(tenant, minutes_ago=5)

        worker_tasks.dispatch_due_scheduled_jobs.delay()

        job.refresh_from_db()
        assert job.started_at is not None


class TestNotificationSweepRoundTrip:
    """``dispatch-pending-notifications`` from beat entry to open socket."""

    def test_a_persisted_notification_reaches_the_socket_and_is_flagged(self):
        """The T22 push/flip split, driven by a job instead of by a request.

        The task publishes; the consumer writes ``delivered``. So the socket
        receives the row and only then does the flag move — and if no socket
        were connected the row would stay ``delivered=False`` and be swept
        again, which is the recovery path that makes a lost push survivable.

        The whole interaction lives inside one coroutine, as the consumer suite
        does: ``async_to_sync`` runs each scenario on its own event loop in its
        own thread, and the consumer's task together with the channel-layer
        queues it awaits are bound to the loop that first ran it. Splitting the
        connect and the receive into two ``_run`` calls leaves the second one
        waiting on a loop that owns nothing.
        """
        from asgiref.sync import sync_to_async

        tenant = _make_tenant("Sweep Hospital")
        user = _make_user(tenant, "sweep-nurse")
        token = _access_token(user)
        row = Notification.objects.create(
            tenant_id=tenant.id,
            user_id=uuid.UUID(int=user.pk),
            title="Critical potassium",
            body="Recheck before the next dose.",
            type="alert",
            persisted=True,
            delivered=False,
        )

        async def scenario():
            communicator = WebsocketCommunicator(
                application, f"{NOTIFICATIONS_WS}?token={token}"
            )
            connected, _ = await communicator.connect()
            assert connected is True
            await sync_to_async(worker_tasks.dispatch_pending_notifications.delay)()
            message = await communicator.receive_json_from(timeout=5)
            await communicator.disconnect()
            return message

        message = _run(scenario)

        assert message["id"] == str(row.id)
        row.refresh_from_db()
        assert row.delivered is True
        assert row.persisted is True

    def test_an_already_delivered_notification_is_not_pushed_again(self):
        """The sweep selects ``delivered=False``, so a delivered row is never
        re-published; a notification the user already saw stays seen."""
        from asgiref.sync import sync_to_async

        tenant = _make_tenant("Quiet Hospital")
        user = _make_user(tenant, "quiet-nurse")
        token = _access_token(user)
        row = Notification.objects.create(
            tenant_id=tenant.id,
            user_id=uuid.UUID(int=user.pk),
            title="Old news",
            body="Already read.",
            type="info",
            persisted=True,
            delivered=True,
        )

        async def scenario():
            communicator = WebsocketCommunicator(
                application, f"{NOTIFICATIONS_WS}?token={token}"
            )
            connected, _ = await communicator.connect()
            assert connected is True
            report = await sync_to_async(worker_tasks.dispatch_pending_notifications.delay)()
            await communicator.disconnect()
            return report

        report = _run(scenario)

        assert report.result["enqueued"] == 0
        row.refresh_from_db()
        assert row.delivered is True
