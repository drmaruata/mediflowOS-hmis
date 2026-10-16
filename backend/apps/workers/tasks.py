"""Workers — Celery tasks (PLT-004, INT-014, AUD-004, ABD-014, PLT-001).

Two families of task live here, and the split is the whole design:

* **per-tenant tasks** — ``dispatch_notification``, ``purge_expired_audit_events``,
  ``run_scheduled_job`` and ``scan_abdm_callback_failures``. Each takes its tenant
  context explicitly, opens its own ``transaction.atomic()`` and calls
  ``bind_tenant_session`` *inside* it. ``set_config(..., is_local=true)`` is
  transaction-scoped, so binding outside the block would be silently discarded and
  the queries would run unscoped.

* **dispatchers** — the ``dispatch_*`` tasks the beat schedule points at. A static
  ``CELERY_BEAT_SCHEDULE`` is frozen at settings import while tenants are created
  at runtime, so the schedule cannot carry a tenant id. Each dispatcher is
  therefore zero-argument: it enumerates the tenants and enqueues the per-tenant
  task over them.

Every task carries the same retry policy below and an idempotency guard, because
a task that may be retried must not double-write: the notification sweep leaves
``delivered`` to the consumer, the job claim is a conditional UPDATE, the purge is
a delete, and the ABDM alert matches a constant title inside its window. The
permanent no-op paths return instead of raising, so ``autoretry_for`` never spins
on a condition retrying cannot fix.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from common.tenant import bind_tenant_session

logger = logging.getLogger(__name__)


#: Retry policy shared by every task (PLT-004). One dict so a task added later
#: cannot quietly land with a different policy; the test suite asserts these
#: attributes on every registered task, which is the backstop for a task written
#: without it.
RETRY_POLICY = {
    "autoretry_for": (Exception,),
    "max_retries": 5,
    # Exponential: Celery waits ``2 ** retries`` seconds — 2s, 4s, 8s, 16s, 32s.
    "retry_backoff": True,
    # Pinned rather than inherited so an upstream default change cannot silently
    # stretch a retry storm. ``retry_jitter`` is deliberately left unset: Celery
    # enables it by default, and jitter is what stops every worker for one tenant
    # retrying in lockstep.
    "retry_backoff_max": 600,
}

#: How many tenants one dispatcher run will fan out over. A dispatcher is a
#: single Celery message, so a deployment large enough to exceed this has to notice
#: — the result carries ``truncated`` — rather than silently sweep a fixed prefix.
TENANT_ENUMERATION_LIMIT = 500

#: How many due ``platform.scheduled_job`` rows one dispatcher run claims per
#: tenant. One hospital's backlog must not crowd every other hospital's jobs out
#: of a single message; the remainder is picked up on the next pass.
DUE_JOB_LIMIT = 100

#: How many undelivered notifications one dispatcher run pushes per tenant, for
#: the same reason. A row past the bound is swept again, which is safe because the
#: only thing that clears a row is a consumer receiving it.
PENDING_NOTIFICATION_LIMIT = 100

#: ABD-014: how far back the scan looks. Long enough that a burst of rejections is
#: a signal rather than a spike, short enough that the same burst does not
#: suppress a fresh alert after the fact — the window is both what is counted and
#: what makes the alert idempotent.
FAILURE_WINDOW = timedelta(hours=1)

#: ABD-014: how many rejections inside the window constitute "abnormal". The
#: gateway refuses a bad call cheaply (an HMAC mismatch costs one hash), so a real
#: misconfiguration shows up as a burst within minutes and single bad calls are
#: not an incident. The beat entry runs this hourly, so every hour is covered once.
FAILURE_THRESHOLD = 5

#: ABD-014: the alert title. Deliberately a constant rather than a message
#: carrying the count: it is the key the idempotency guard matches on, so a second
#: run in the same window can recognise "this burst was already reported" instead
#: of counting on the text to be identical.
CALLBACK_FAILURE_ALERT_TITLE = "ABDM callback failure burst"

#: ABD-014: what counts as a failure. ``ABHACallbackLog.status`` already carries
#: ``rejected``, but **no writer emits it today** — the callback view refuses an
#: unauthenticated, malformed, stale or unknown-facility call before any ledger
#: row exists, and the "no OPD department" refusal returns from inside the atomic
#: block before the row is written. So this scan counts what the ledger records
#: and stays empty until a writer records rejections. That is a statement about
#: what is instrumented, not a defect to paper over.
FAILURE_STATUS = "rejected"


@shared_task(**RETRY_POLICY)
def dispatch_notification(notification_id, tenant_id):
    """Push one persisted notification to its tenant's sockets (PLT-001, INT-012).

    The tenant is an explicit argument rather than being read off the row, because
    ``platform.notification`` carries a ``tenant_isolation`` policy whose predicate
    is ``tenant_id = current_setting('app.tenant_id')`` and which fails closed when
    the setting is unset. Reading the row *first* to discover its tenant would
    therefore return nothing on PostgreSQL and the task would treat every real
    notification as missing — working in the SQLite suite and nowhere else. The
    lookup naming both ids also means a fabricated id belonging to another
    hospital matches nothing.

    ``delivered`` is *not* flipped here. The flip belongs to the consumer that
    actually sends the frame: a task that marked the row delivered would claim
    success for a push that may have reached no socket, and the row would then be
    excluded from every later sweep. With no socket connected the row stays
    ``delivered=False``, which is both the honest state and the one that gets it
    swept again.
    """
    with transaction.atomic():
        bind_tenant_session(str(tenant_id))

        # Imported inside the task: this module is imported by Celery's autodiscovery
        # while the app registry is still being populated.
        from apps.platform.models import Notification
        from apps.platform.serializers import NotificationSerializer
        from apps.platform.views import _push_notification

        notification = (
            Notification.objects.filter(id=notification_id, tenant_id=tenant_id).first()
        )
        if notification is None:
            logger.info(
                "notification %s not found for tenant %s; nothing to push",
                notification_id,
                tenant_id,
            )
            return _dispatch_result(
                notification_id,
                tenant_id,
                pushed=False,
                reason="no such notification row",
            )
        if notification.delivered:
            # Already pushed and received: a second frame would re-open a
            # notification the user has already seen.
            return _dispatch_result(
                notification_id,
                tenant_id,
                pushed=False,
                reason="already delivered",
            )

        # Reused rather than reimplemented so this and the view's push path cannot
        # drift apart. It logs and swallows a channel-layer failure by design:
        # the row is already committed, so raising would turn a succeeded write
        # into a 500 and the client would retry it into a duplicate. A failed push
        # leaves ``delivered`` False, so the next sweep picks the row up again.
        _push_notification(str(tenant_id), NotificationSerializer(notification).data)

    return _dispatch_result(notification_id, tenant_id, pushed=True)


@shared_task(**RETRY_POLICY)
def purge_expired_audit_events(tenant_id):
    """Delete this tenant's audit events past the retention window (AUD-004).

    Scheduled nightly off-peak. The window is resolved inside
    :func:`purge_expired` from ``settings.AUDIT_RETENTION_DAYS``, so a scheduled
    job cannot run with a different window than the operator configured.

    Idempotent by nature: the second run finds nothing inside the window and
    deletes zero. ``audit.event`` is RLS-protected, so the binding below is what
    makes the delete land on this tenant's rows and only those.
    """
    from apps.audit.services import purge_expired

    # The binding must live inside the transaction: ``set_config(...,
    # is_local=true)`` is transaction-scoped, so binding outside the block would
    # be discarded and the queries would run with no tenant context at all.
    with transaction.atomic():
        bind_tenant_session(str(tenant_id))
        deleted = purge_expired(tenant_id=tenant_id)

    return {"tenant_id": str(tenant_id), "deleted": deleted}


@shared_task(**RETRY_POLICY)
def run_scheduled_job(job_id):
    """Claim one due ``platform.scheduled_job`` row and run it (PLT-004).

    ``platform.scheduled_job`` carries no RLS policy, so the row is resolved first
    and its own tenant becomes the session context. Application scoping is
    therefore the only control on this table, and every write below is filtered by
    ``row.tenant_id`` so the row's tenant bounds the whole run.

    Re-entrancy is the claim: a single conditional ``UPDATE``. A row already
    claimed updates zero rows and the task returns, so a scheduler that fires
    twice, or a worker that replays the message, executes the job once. The claim
    must stay a conditional UPDATE rather than a read-then-write — two workers
    reading ``pending`` would both proceed.

    In R1 no ``job_type`` has an implementation (see ``_JOB_HANDLERS``), so a
    claimed job is parked as ``failed`` with a reason: a parked job must not sit
    ``running`` forever with no result, which would hide a real starvation from
    the very visibility surface PLT-004 asks for.
    """
    from apps.platform.models import ScheduledJob

    with transaction.atomic():
        row = (
            ScheduledJob.objects.filter(id=job_id)
            .values("id", "tenant_id", "job_type")
            .first()
        )
        if row is None:
            logger.warning("scheduled job %s not found; nothing to run", job_id)
            return _job_result(job_id, ran=False, status="missing")

        bind_tenant_session(str(row["tenant_id"]))
        claimed = ScheduledJob.objects.filter(
            id=row["id"], tenant_id=row["tenant_id"], status="pending"
        ).update(status="running", started_at=timezone.now())
        if not claimed:
            status = (
                ScheduledJob.objects.filter(id=row["id"])
                .values_list("status", flat=True)
                .first()
            )
            return _job_result(
                job_id,
                ran=False,
                status=status,
                tenant_id=row["tenant_id"],
                reason="already claimed",
            )

        # R1 ships no engine for any job_type — the indicator engine, the
        # report generator and the async callback re-processor are all post-R1.
        # The claim above is still real work: it is what a future handler will be
        # invoked under, and it stops a scheduler double-running a job meanwhile.
        reason = f"{row['job_type']} has no R1 implementation — engine deferred"
        ScheduledJob.objects.filter(id=row["id"], tenant_id=row["tenant_id"]).update(
            status="failed",
            completed_at=timezone.now(),
            result={"reason": reason},
        )
        logger.info(
            "scheduled job %s (%s) parked: %s",
            job_id,
            row["job_type"],
            reason,
        )
        return _job_result(
            job_id,
            ran=False,
            status="failed",
            tenant_id=row["tenant_id"],
            job_type=row["job_type"],
            reason=reason,
        )


@shared_task(**RETRY_POLICY)
def scan_abdm_callback_failures(tenant_id):
    """Alert a tenant's administrators on a burst of ABDM callback failures (ABD-014).

    The tenant id is an explicit argument and every query, count and write below is
    scoped by it, so one tenant's burst can neither raise an alert in another
    tenant nor read its rows.

    The alert is a ``platform.notification`` per active membership whose role is
    privileged — ``Role.require_mfa`` is the documented privileged-role marker
    (TEN-006) and the predicate the TEN-007 break-glass alert already fans out
    over, so ABD-014 uses one predicate instead of a second one. The body carries
    the count and the window only: a burst is an operational event, not a clinical
    one, so no patient, ABHA number or request id reaches a row a notification
    screen reads.

    Idempotent by design: within one window the guard is "a critical alert with
    this title already exists", so a scheduler that runs twice raises one alert
    rather than one per run. A burst in a later hour does alert again.
    """
    window_start = timezone.now() - FAILURE_WINDOW

    # The binding must live inside the transaction: ``set_config(...,
    # is_local=true)`` is transaction-scoped, so binding outside the block would
    # be discarded and the queries would run with no tenant context at all.
    with transaction.atomic():
        bind_tenant_session(tenant_id)

        from apps.abdm_gateway.models import ABHACallbackLog
        from apps.identity_tenancy.models import UserMembership
        from apps.platform.models import Notification

        failures = (
            ABHACallbackLog.objects.filter(
                tenant_id=tenant_id,
                status=FAILURE_STATUS,
                timestamp__gte=window_start,
            )
            .count()
        )
        if failures < FAILURE_THRESHOLD:
            return _scan_result(tenant_id, failures, alerted=False)

        if Notification.objects.filter(
            tenant_id=tenant_id,
            type="critical",
            title=CALLBACK_FAILURE_ALERT_TITLE,
            created_at__gte=window_start,
        ).exists():
            # Already reported inside this window: nothing to add. This is the
            # whole of the idempotency guard, and why the title is a constant.
            return _scan_result(tenant_id, failures, alerted=False)

        recipients = list(
            UserMembership.objects.filter(
                tenant_id=tenant_id, active=True, role__require_mfa=True
            )
        )
        if not recipients:
            # Zero administrators is a configuration gap, not a reason to stay
            # quiet: log the tenant and the count so the burst is still visible,
            # and crash nothing — an exception here would retry a scan whose
            # result will not change until someone fixes the roles.
            logger.warning(
                "ABDM callback failure burst: tenant %s had %d rejected "
                "callbacks in the last hour but no administrator to alert",
                tenant_id,
                failures,
            )
            return _scan_result(tenant_id, failures, alerted=False)

        body = (
            f"{failures} ABDM profile-share callbacks were rejected in the "
            f"last {int(FAILURE_WINDOW.total_seconds() // 60)} minutes "
            f"(threshold {FAILURE_THRESHOLD}). Inspect the gateway signature, "
            f"clock skew and target facility configuration."
        )
        for membership in recipients:
            Notification.objects.create(
                tenant_id=tenant_id,
                user_id=membership.user_id,
                title=CALLBACK_FAILURE_ALERT_TITLE,
                body=body,
                type="critical",
                # Persisted before delivery: the consumer flips ``delivered``
                # when it actually pushes, as the TEN-007 alert does.
                persisted=True,
                delivered=False,
            )
        logger.info(
            "ABDM callback failure burst: tenant %s, %d rejected callbacks in "
            "the last hour, %d administrators alerted",
            tenant_id,
            failures,
            len(recipients),
        )
        return _scan_result(tenant_id, failures, alerted=True)


@shared_task(**RETRY_POLICY)
def dispatch_audit_retention_purge():
    """Beat entry ``purge-expired-audit-events``: nightly retention sweep.

    A static ``CELERY_BEAT_SCHEDULE`` cannot carry tenant ids, so it points here
    and this task enumerates them. That is also why the sweep is a pass over
    tenants and not a single query: ``audit.event`` is RLS-protected, so each
    purge must run inside its own bound session — a job that did not bind would
    delete nothing while looking like it worked.
    """
    tenants, bound = _tenant_plan()
    for tenant_id in tenants:
        purge_expired_audit_events.delay(tenant_id)
    return _dispatch_report("purge-expired-audit-events", len(tenants), len(tenants), bound)


@shared_task(**RETRY_POLICY)
def dispatch_abdm_callback_failure_scan():
    """Beat entry ``scan-abdm-callback-failures``: hourly ABD-014 sweep.

    Hourly because the scan's own window is an hour: a shorter cadence would
    re-count the same burst inside the same window and be swallowed by the
    title-constant idempotency guard anyway.
    """
    tenants, bound = _tenant_plan()
    for tenant_id in tenants:
        scan_abdm_callback_failures.delay(tenant_id)
    return _dispatch_report(
        "scan-abdm-callback-failures", len(tenants), len(tenants), bound
    )


@shared_task(**RETRY_POLICY)
def dispatch_due_scheduled_jobs():
    """Beat entry ``run-due-scheduled-jobs``: enqueue every job whose time came.

    Every five minutes: a job row carries its own ``scheduled_at``, so the sweep
    only has to be frequent enough that a due job is picked up promptly. Finer
    would hammer the broker for jobs that cannot run yet; coarser would leave a
    job scheduled for 09:00 waiting until 09:10.
    """
    now = timezone.now()
    tenants, bound = _tenant_plan()
    enqueued = 0
    for tenant_id in tenants:
        # Collected and committed *before* the enqueue: a ``.delay()`` issued
        # inside this transaction would, under ``CELERY_TASK_ALWAYS_EAGER``, run
        # the job inside the dispatcher's own transaction as a nested savepoint.
        for job_id in _due_job_ids(tenant_id, now):
            run_scheduled_job.delay(str(job_id))
            enqueued += 1
    return _dispatch_report("run-due-scheduled-jobs", len(tenants), enqueued, bound)


@shared_task(**RETRY_POLICY)
def dispatch_pending_notifications():
    """Beat entry ``dispatch-pending-notifications``: push every undelivered row.

    Every minute, because these are clinical alerts a provider is waiting on
    (PLT-001) and the sweep is one filtered, bounded read per tenant. This is also
    the recovery path for a failed push: the consumer is what flips ``delivered``,
    so a row no socket ever received is swept again on the next pass.
    """
    tenants, bound = _tenant_plan()
    enqueued = 0
    for tenant_id in tenants:
        for notification_id in _undelivered_notification_ids(tenant_id):
            dispatch_notification.delay(str(notification_id), tenant_id)
            enqueued += 1
    return _dispatch_report(
        "dispatch-pending-notifications", len(tenants), enqueued, bound
    )


def _tenant_plan(bound=TENANT_ENUMERATION_LIMIT):
    """The tenants one dispatcher run will fan out over, and the bound applied.

    ``identity.tenant`` is the one table with no ``tenant_id`` column and no RLS
    policy — it is the tenancy root, and the platform administrator has to list
    every tenant to onboard one (TEN-010) — so this read needs no bound session.
    Everything the dispatchers read afterwards is RLS-protected or tenant-owned,
    so each per-tenant step rebinds before it queries.

    Ordered by ``(created_at, id)`` so the bounded prefix is stable between runs:
    a tenant created early is not skipped on one pass and swept on the next. The
    bound is what makes an over-large deployment visible instead of silently
    under-swept — see ``_dispatch_report``.
    """
    from apps.identity_tenancy.models import Tenant

    tenants = [
        str(tenant_id)
        for tenant_id in Tenant.objects.order_by("created_at", "id").values_list(
            "id", flat=True
        )[:bound]
    ]
    return tenants, bound


def _due_job_ids(tenant_id, now, limit=DUE_JOB_LIMIT):
    """Ids of this tenant's pending jobs whose ``scheduled_at`` has passed.

    Scoped by tenant at the application level, because ``platform.scheduled_job``
    has no RLS policy and a filter is the only thing keeping one hospital's queue
    out of another's sweep. Oldest waiting job claimed first.
    """
    from apps.platform.models import ScheduledJob

    with transaction.atomic():
        bind_tenant_session(tenant_id)
        return list(
            ScheduledJob.objects.filter(
                tenant_id=tenant_id, status="pending", scheduled_at__lte=now
            )
            .order_by("scheduled_at", "id")
            .values_list("id", flat=True)[:limit]
        )


def _undelivered_notification_ids(tenant_id, limit=PENDING_NOTIFICATION_LIMIT):
    """Ids of this tenant's persisted-but-undelivered notifications.

    Scoped by tenant both in the filter and through the session binding, since
    ``platform.notification`` is RLS-protected: the binding is what makes the
    query return this tenant's rows at all. Ordered by ``created_at`` so the
    oldest unread alert is pushed first.
    """
    from apps.platform.models import Notification

    with transaction.atomic():
        bind_tenant_session(tenant_id)
        return list(
            Notification.objects.filter(
                tenant_id=tenant_id, persisted=True, delivered=False
            )
            .order_by("created_at", "id")
            .values_list("id", flat=True)[:limit]
        )


def _dispatch_report(schedule, tenants, enqueued, bound):
    """What a dispatcher run did — PLT-004's visibility half.

    ``truncated`` is the operator's signal that the bound was hit and another
    pass is needed. Counts and ids only: a task result lives in a backend that may
    sit outside the hospital's boundary, so it carries no notification body and no
    audit content (the :func:`_scan_result` convention).
    """
    return {
        "schedule": schedule,
        "tenants": tenants,
        "enqueued": enqueued,
        "truncated": tenants >= bound,
    }


def _dispatch_result(notification_id, tenant_id, *, pushed, reason=None):
    """The dispatch task's return value: whether a frame went out, and why not."""
    result = {
        "tenant_id": str(tenant_id),
        "notification_id": str(notification_id),
        "pushed": pushed,
    }
    if reason is not None:
        result["reason"] = reason
    return result


def _job_result(job_id, *, ran, status, tenant_id=None, job_type=None, reason=None):
    """The job task's return value: the terminal state, and nothing else.

    Counts and ids only (the :func:`_scan_result` convention): a task result is
    stored in a backend that may sit outside the hospital's boundary, so it carries
    no job payload, no patient reference and no report content.
    """
    result = {"job_id": str(job_id), "ran": ran, "status": status}
    if tenant_id is not None:
        result["tenant_id"] = str(tenant_id)
    if job_type is not None:
        result["job_type"] = job_type
    if reason is not None:
        result["reason"] = reason
    return result


def _scan_result(tenant_id, failures, *, alerted):
    """The task's return value: what it saw and whether it raised an alert.

    Counts and ids only — the ledger rows themselves are never read into the
    result, so a result stored outside the hospital's boundary cannot carry
    callback payloads.
    """
    return {
        "tenant_id": str(tenant_id),
        "failures": failures,
        "alerted": alerted,
    }
