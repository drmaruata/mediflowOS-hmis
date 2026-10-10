"""Audit services (AUD-001).

Reads are audited alongside writes. Write events hang off a serializer save
through ``TenantScopedQuerysetMixin._write_audit_log``; a read has no save to
hang off — it happens in a plain view method (``PatientViewSet.retrieve`` /
``search``) — so it needs a free function that takes the instance and the
request directly.
"""
from common.tenant import REQUEST_TENANT_ATTR
from .models import AuditEvent


def audit_read(instance, request):
    """Record that ``request`` read ``instance`` (AUD-001, read half).

    Writes an ``AuditEvent(action="read")`` naming the row by its table
    (``instance._meta.db_table`` → ``registry.patient``) and stringified pk,
    matching the shape ``TenantScopedQuerysetMixin._write_audit_log`` gives
    write rows. The tenant comes from the request's resolved context, never
    from the client; an unresolved tenant writes nothing at all, mirroring the
    mixin — an audit row with no tenant would be an unscoped row no RLS policy
    could read back.

    The write is synchronous and inside the request transaction. Read
    completeness is a safety net, so it is chosen over read latency: a read
    that returned data but failed to record would leave a gap in the trail,
    and moving the write out of the transaction would let the response win the
    race. Volume is bounded by the read rate and, for ``search``, by the
    returned page size. If read volume ever grows enough to matter, a future
    task may batch or stream these writes — until then, this stays synchronous.

    No PHI lands in the row: ``entity_type`` is the table name and
    ``entity_id`` the pk, both identifiers. Patient demographics, identifiers
    and free text are never passed here and must never be.
    """
    tenant_id = getattr(request, REQUEST_TENANT_ATTR, None)
    if not tenant_id:
        return

    AuditEvent.objects.create(
        tenant_id=tenant_id,
        user_id=request.user.pk if request.user.is_authenticated else None,
        action="read",
        entity_type=instance._meta.db_table,
        entity_id=str(instance.pk),
        source_ip=request.META.get("REMOTE_ADDR"),
    )
