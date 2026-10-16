"""Per-tenant feature flag reads (PLT-006).

The read side of a feature flag: is the feature on for *this* tenant, and what
happens when the question cannot be answered. That is this module's whole
surface. The one thing a caller must know - the helper binds the tenant itself,
so a nested call rebinds the enclosing transaction - is in
:func:`flag_enabled`.
"""
import logging

from django.db import transaction

from common.tenant import bind_tenant_session

from .models import FeatureFlag

logger = logging.getLogger(__name__)


def flag_enabled(tenant_id, key) -> bool:
    """Whether ``key`` is switched on for ``tenant_id`` (PLT-006).

    Fails closed: an unknown key, an unknown or unusable tenant, and any error at
    all answer ``False``. A flag that cannot be read is not evidence the feature
    is wanted, so "cannot tell" resolves as "off"; raising would turn a
    configuration lookup into a 500 on whatever clinical screen consulted it, and
    anything but ``False`` on error would switch a feature on for every tenant.

    **The tenant is bound here, not by the caller.** ``platform.feature_flag`` is
    RLS-protected and its policy reads ``app.tenant_id``, a *transaction-scoped*
    setting. An unbound query returns zero rows on PostgreSQL rather than raising,
    so a helper relying on its caller to bind would report every feature off in
    production - silently, since the fast suite runs on SQLite, where there is no
    policy to get wrong. Hence the ``atomic()``: a worker or Celery task gets the
    right answer without knowing any of this.

    **A nested call rebinds the caller's transaction, and that is the contract.**
    ``set_config(..., is_local=true)`` is ``SET LOCAL``, which PostgreSQL scopes to
    the **transaction**, not to the savepoint a nested ``atomic()`` opens: the
    effects survive releasing that savepoint (the pre-8.3 behaviour that scoped it
    to the savepoint was changed as unintuitive), so ``flag_enabled(other, ...)``
    inside a transaction bound to ``tenant_a`` leaves it bound to ``other`` for
    everything that follows.

    Documented rather than refused, deliberately. The contract: a caller needing
    the answer for a tenant other than the bound one must ask outside the
    transaction it still needs bound to its own. Breaking it is bounded and
    fail-closed - reads under the wrong policy return nothing and writes are
    refused by the policy's ``WITH CHECK``, so rows neither leak nor silently land
    under another tenant. Refusing was rejected because detecting the existing
    binding means a PostgreSQL-only ``current_setting`` read, untestable on the
    SQLite fast suite; because a refusal would make the answer depend on caller
    context, answering "off" for a reason unrelated to the flag; and because a
    guard in front of the bind re-adds the branch ``atomic()`` exists to remove,
    leaving the refused caller reading under whatever binding the session had
    (on a worker, none) and seeing every feature off.

    Uncached deliberately: a cached answer needs invalidation across processes and
    the safe default is already cheap. Hot paths should hold the value for the
    request rather than asking once per row.
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
        # Logged, never propagated, and by tenant and key rather than by traceback:
        # the exception's own message quotes the offending value - on a malformed
        # tenant argument, whatever the caller passed - so ``exc_info`` stays off,
        # for the same reason ``apps.platform.views._discard_upload`` leaves it off.
        logger.warning(
            "feature flag lookup failed tenant_id=%s key=%s error=%s",
            tenant_id,
            key,
            type(exc).__name__,
        )
        return False
