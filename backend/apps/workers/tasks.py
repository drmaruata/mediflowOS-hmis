"""Workers — Celery tasks."""
import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from common.tenant import bind_tenant_session

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def compute_indicators(self, tenant_id, period_start, period_end):
    """Nightly indicator computation for a tenant."""
    # Placeholder — will be implemented with the indicator engine
    pass


@shared_task(bind=True, max_retries=3)
def sync_abdm_callback(self, callback_id):
    """Process ABDM callback asynchronously."""
    pass


@shared_task(bind=True, max_retries=3)
def send_notification(self, tenant_id, payload):
    """Send a notification via the notification engine."""
    pass


#: ABD-014: how far back the scan looks. One hour is long enough that a burst
#: of rejections is a signal rather than a spike, and short enough that the
#: same burst does not suppress a fresh alert after the fact — the window is
#: both what is counted and what makes the alert idempotent.
FAILURE_WINDOW = timedelta(hours=1)

#: ABD-014: how many rejections inside the window constitute "abnormal". The
#: gateway refuses a bad call cheaply (an HMAC mismatch costs one hash), so a
#: real misconfiguration or an abusive sender shows up as a burst within
#: minutes, and single bad calls from a misbehaving source app are not an
#: incident. Task 23 wires the schedule; nothing runs this until then.
FAILURE_THRESHOLD = 5

#: ABD-014: the alert title. Deliberately a constant rather than a message
#: carrying the count: it is the key the idempotency guard matches on, so a
#: second run in the same window can recognise "this burst was already
#: reported" instead of counting on the text to be identical.
CALLBACK_FAILURE_ALERT_TITLE = "ABDM callback failure burst"

#: ABD-014: what counts as a failure when counting. ``ABHACallbackLog.status``
#: already carries ``rejected``, but no writer emits it today — the callback
#: view refuses an unauthenticated, malformed, stale or unknown-facility call
#: before any ledger row exists, and the "no OPD department" refusal returns
#: from inside the atomic block before the row is written. So this scan is
#: deliberately forward-looking: it counts what the ledger records, and the
#: count stays empty until a writer records rejections. That is a statement
#: about what is instrumented, not a defect to paper over.
FAILURE_STATUS = "rejected"


@shared_task
def task_scan_callback_failures(tenant_id):
    """Alert a tenant's administrators on a burst of ABDM callback failures (ABD-014).

    The tenant id is an explicit argument (AGENTS.md async rule: a task never
    runs without tenant context) and every query, count and write below is
    scoped by it, so one tenant's burst can neither raise an alert in another
    tenant nor read its rows.

    The alert is a ``platform.notification`` per active membership whose role
    is privileged — ``Role.require_mfa`` is the documented privileged-role
    marker (TEN-006) and is the predicate the TEN-007 break-glass alert already
    fans out over, so ABD-014 uses one predicate instead of a second one. The
    body carries the count and the window only: a burst is an operational
    event, not a clinical one, so no patient, ABHA number, request id or
    demographic value is written into a row that a notification screen reads.

    Idempotent by design (a retried task must not double-write): within one
    window the guard is "a critical alert with this title already exists", so
    a scheduler that runs twice, or a worker that replays the task, raises one
    alert rather than one per run. A burst in a later hour is outside the
    earlier window and does alert again.
    """
    window_start = timezone.now() - FAILURE_WINDOW

    # The session binding has to live inside the transaction (see
    # common/tenant.py): ``set_config(..., is_local=true)`` is
    # transaction-scoped, so binding outside the block would be discarded and
    # the queries would run with no tenant context at all.
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
            # whole of the idempotency guard, and it is why the title is a
            # constant.
            return _scan_result(tenant_id, failures, alerted=False)

        recipients = list(
            UserMembership.objects.filter(
                tenant_id=tenant_id, active=True, role__require_mfa=True
            )
        )
        if not recipients:
            # Zero administrators is a configuration gap, not a reason to
            # stay quiet: log the tenant and the count so the burst is still
            # visible in the logs, and crash nothing — an exception here would
            # retry a scan whose result will not change until someone fixes
            # the roles.
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
                # Persisted before delivery: the delivery consumer flips
                # ``delivered`` when it actually pushes, exactly as the
                # TEN-007 break-glass alert does.
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


def _scan_result(tenant_id, failures, *, alerted):
    """The task's return value: what it saw and whether it raised an alert.

    Counts and ids only — the ledger rows themselves are never read into the
    result, so a task result stored in a backend outside the hospital's
    boundary cannot carry callback payloads.
    """
    return {
        "tenant_id": str(tenant_id),
        "failures": failures,
        "alerted": alerted,
    }
