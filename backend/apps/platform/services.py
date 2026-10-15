"""Per-tenant feature flag reads (PLT-006).

The read side of a feature flag is a decision every code path needs and no code
path should have to remember how to make safely: is the feature on for *this*
tenant, on no other tenant's terms, and what happens when the question cannot be
answered. That is this module's whole surface.

The one thing a caller has to know - the helper binds the tenant itself, and a
nested call therefore rebinds the enclosing transaction - is in
:func:`flag_enabled`'s docstring rather than here, next to the reason it has to
be that way.
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

    **A nested call rebinds the caller's transaction, and that is the contract.**
    ``set_config(..., is_local=true)`` is ``SET LOCAL``, which PostgreSQL scopes
    to the **transaction**, not to the savepoint a nested ``atomic()`` opens: the
    effects survive releasing that savepoint and last until the enclosing
    transaction ends. (The PostgreSQL command reference records the change on
    this directly - "the effects of a SET LOCAL would be canceled by releasing
    an earlier savepoint" was the 8.0-8.2 behaviour, "changed because it was
    deemed unintuitive" - so the older intuition that a savepoint scopes a
    setting is not one to rely on.) So ``flag_enabled(other_tenant, ...)``
    called inside a transaction already bound to ``tenant_a`` leaves that
    transaction bound to ``other_tenant`` for everything that follows, and the
    caller's own subsequent statements run under the wrong policy.

    Documented rather than refused, deliberately. The caller contract is: **a
    caller that needs the answer for a tenant other than the one it is bound to
    must ask outside the transaction it still needs bound to its own** - or not
    nest. What that costs if the contract is broken is bounded and fail-closed:
    reads under the wrong policy return nothing and writes are refused by the
    policy's ``WITH CHECK``, so the caller's own rows neither leak nor silently
    land under another tenant - the write raises instead. Refusing was the
    alternative and was rejected for three reasons. Detecting the existing
    binding means reading ``current_setting`` on every call, which is
    PostgreSQL-only and so untestable on the SQLite the fast suite runs. A
    refusal also makes the answer depend on the caller's context, so "is the
    flag on for that other hospital?" would answer "off" for a reason that has
    nothing to do with the flag. And a guard in front of the bind adds exactly
    the branch the ``atomic()`` above exists to remove: the refused caller goes
    on reading under whatever binding the session had - on a worker, none - and
    sees every feature reported off. Nothing in the codebase asks about a second
    tenant today, so the hazard is a contract rather than a live defect.

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
