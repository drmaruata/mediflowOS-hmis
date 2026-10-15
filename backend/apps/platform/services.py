"""Per-tenant feature flag reads (PLT-006).

The read side of a feature flag is a decision every code path needs and no code
path should have to remember how to make safely: is the feature on for *this*
tenant, on no other tenant's terms, and what happens when the question cannot be
answered. That is this module's whole surface.
"""
import logging

from django.db import transaction

from common.tenant import bind_tenant_session

from .models import FeatureFlag

logger = logging.getLogger(__name__)


def flag_enabled(tenant_id, key) -> bool:
    """Whether ``key`` is switched on for ``tenant_id`` (PLT-006).

    Fails closed: an unknown key, an unknown or unusable tenant, and any error at
    all answer ``False``. The asymmetry is deliberate and is the whole contract.
    A configuration flag that cannot be read is not evidence that a feature is
    wanted - a hospital that has never heard of the feature has not opted into
    it - so "cannot tell" is resolved as "off". Raising instead would turn a
    configuration lookup into a 500 on whatever clinical screen consulted it, and
    returning anything but ``False`` on an error would switch a feature on for
    every tenant at once.

    **The tenant is bound here, not by the caller.** ``platform.feature_flag`` is
    RLS-protected and its policy reads ``app.tenant_id``, which is a
    *transaction-scoped* setting (see ``common/tenant.py``). A query issued with
    no binding returns zero rows on PostgreSQL rather than raising, so a helper
    that relied on its caller to bind would report every feature off in
    production - silently, since the fast suite runs on SQLite, where there is no
    policy and no binding to get wrong. Hence the ``atomic()`` block here: a
    worker, a Celery task or any non-request caller gets the right answer without
    knowing any of this.

    A nested block (a view under ``ATOMIC_REQUESTS``, a caller that already opened
    one) becomes a savepoint and the setting is scoped to it, so the read inside
    the block still sees it.

    This is a database read per call and deliberately uncached: a cached answer
    would need invalidation across processes, and the safe default is already
    cheap. Callers on a hot path should hold the value for the request rather than
    asking once per row.
    """
    if not tenant_id or not key:
        # Refused before touching the database: an absent tenant is not a tenant
        # to look rows up under, and an absent key is not a feature.
        return False
    try:
        with transaction.atomic():
            bind_tenant_session(str(tenant_id))
            row = (
                FeatureFlag.objects.filter(tenant_id=tenant_id, key=key)
                .only("enabled")
                .first()
            )
            return bool(row and row.enabled)
    except Exception as exc:
        # Logged, never propagated, and by tenant and key rather than by
        # traceback: a flag name is configuration, not patient data, but the
        # exception's own message quotes the offending value - which on a
        # malformed tenant argument is whatever the caller passed - so
        # ``exc_info`` is left off for the same reason
        # ``apps.platform.views._discard_upload`` leaves it off.
        logger.warning(
            "feature flag lookup failed tenant_id=%s key=%s error=%s",
            tenant_id,
            key,
            type(exc).__name__,
        )
        return False