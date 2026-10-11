"""Audit services (AUD-001 to AUD-004).

Reads are audited alongside writes. Write events hang off a serializer save
through ``TenantScopedQuerysetMixin._write_audit_log``; a read has no save to
hang off — it happens in a plain view method (``PatientViewSet.retrieve`` /
``search``) — so it needs a free function that takes the instance and the
request directly.

AUD-002 makes the trail tamper-evident. Every row carries

    hash_chain = HMAC-SHA256(key, prev_hash + canonical(fields))

where ``prev_hash`` is the **same tenant's** most recent event. The chain is
per tenant and strictly ordered, so two tenants writing side by side never
cross-link, and a row commits to everything recorded before it in its own
tenant. Verifying is recomputing: :func:`verify_chain` rebuilds every digest
from the stored columns and names the first row whose recomputed hash does
not match, which is what makes an in-place ``UPDATE`` visible. The ordering
key is the ``auto_now_add`` ``occurred_at`` stamp, so a host clock stepping
backwards between two appends in one tenant would order the rows against
their append order and verify would report a false positive on untouched
rows — a trade-off accepted because the stamp is the only per-row sequence
that survives a worker restart, and the exposure is confined to the tenant
whose host misbehaves. All three writers (the mixin, :func:`audit_read`, and
the QR regenerate path) go through :func:`append_event`, because a row nobody
chains is a gap no verifier can explain.

AUD-004 adds a retention purge. Deleting rows trims the chain, it does not
break it: :func:`verify_chain` re-anchors on the oldest *surviving* chained
row, since a purged predecessor's hash is legitimately gone. See
:func:`purge_expired` for why the purge never rewrites an audit row.
"""
import hashlib
import hmac
import json
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from common.tenant import REQUEST_TENANT_ATTR
from .models import AuditEvent

#: The row columns hashed into the chain — the exact set **both** sides use.
#: :func:`append_event` hashes the caller's kwargs restricted to these names
#: and :func:`verify_chain` rebuilds the same dict from the stored row, so
#: the digest written and the digest recomputed are over the same values.
#:
#: A name left out is unprotected: an in-place ``UPDATE`` of that column
#: would go undetected. ``tenant_id`` is deliberately absent — the chain is
#: already scoped per tenant and the field is what ``append_event`` takes as
#: its keyword-only tenant argument rather than as chained content.
#: ``occurred_at`` is absent because it is not something the event *says*: it
#: is when a clock happened to stamp it, so hashing it would make every
#: digest depend on a value nobody can recompute from the event's own
#: record. ``hash_chain`` is absent because it is what the chain *is*.
CHAIN_FIELDS = (
    "action",
    "entity_id",
    "entity_type",
    "reason",
    "source",
    "source_ip",
    "user_id",
)

#: The coercion each chained value goes through before it is hashed, keyed by
#: field name: the model field's own ``to_python`` — the conversion ``save``
#: performs for every field class here (CharField, GenericIPAddressField and
#: UUIDField all route ``get_prep_value`` through it; the TextField ``reason``
#: keeps an identity ``to_python``, and a non-text ``reason`` cannot be stored
#: at all, so there is no stored value it could disagree with). Hashing the
#: *coerced* value rather than the raw kwarg is what makes the digest written
#: and the digest recomputed from the row agree by construction: writers pass
#: ``auth.User.pk`` as an *integer* while the row stores — and reads back as —
#: ``uuid.UUID(int=<that int>)``, so hashing the raw int would canonicalise
#: to ``5`` while the verifier canonicalises to the UUID string, and no
#: authenticated write could ever verify. ``None`` skips the coercion: every
#: chained column is nullable, and NULL is what an omitted kwarg resolves to.
_CHAIN_COERCE = {
    name: AuditEvent._meta.get_field(name).to_python for name in CHAIN_FIELDS
}


def _canonical_fields(source) -> dict:
    """The canonical field dict for one event, from kwargs or from a row.

    ``source`` is either the writer's kwargs dict or an ``AuditEvent``
    instance; both sides go through this one function. A name the writer
    omitted resolves to ``None``, matching the row's NULL default, so an
    omitted column and a stored NULL hash to the same value. A non-None value
    is coerced through the field's own ``to_python`` (``_CHAIN_COERCE``), so
    the value hashed is the value the row stores whichever side it came from.

    Raises:
        django.core.exceptions.ValidationError: if a chained value cannot be
            coerced — e.g. ``user_id`` that is neither ``None``, a UUID nor
            an integer pk.
    """
    canonical = {}
    for name in CHAIN_FIELDS:
        value = source.get(name) if isinstance(source, dict) else getattr(source, name)
        if value is not None:
            value = _CHAIN_COERCE[name](value)
        canonical[name] = value
    return canonical


def chain_digest(key: str, prev_hash: str, fields: dict) -> str:
    """HMAC-SHA256 over the chained canonical form of one event's fields.

    The signed message is ``prev_hash + canonical(fields)``, where
    ``canonical(fields)`` is
    ``json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)``.

    ``sort_keys`` makes the digest independent of the order the writer
    happened to list fields in; ``separators`` strips the whitespace so
    formatting cannot change it; ``default=str`` makes the non-JSON values
    writers actually pass (a UUID, a datetime — ``None`` is native JSON)
    serialise rather than raise, because a digest that raised would leave the
    row unchained, and a gap in the middle of the chain is exactly what the
    chain exists to prevent.

    Concatenating ``prev_hash`` rather than length-prefixing it is safe here
    because it is a fixed-width 64-character hex sha256, so the boundary
    between it and the JSON cannot be ambiguous.

    Raises:
        ValueError: if ``key`` is empty. An unkeyed HMAC is just a hash, so
            without a key anyone who can recompute it could also forge one
            and the chain would attest nothing.
    """
    if not key:
        raise ValueError(
            "AUDIT_HMAC_KEY is empty: the audit hash chain cannot be computed "
            "or verified without a key (AUD-002)"
        )
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(
        key.encode("utf-8"), (prev_hash + canonical).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _hmac_key() -> str:
    """The chain key, read from settings at call time.

    Read per call rather than captured at import so the settings tests can
    re-import ``config.settings.base`` with the variable unset to pin the
    non-DEBUG guard, and so an operator who rotates the value does not need
    a worker restart to retire the old key. The key is never logged.
    """
    key = getattr(settings, "AUDIT_HMAC_KEY", "")
    if not key:
        raise ValueError(
            "AUDIT_HMAC_KEY is not set: the audit hash chain cannot be "
            "computed or verified without it (AUD-002)"
        )
    return key


def _lock_tenant_chain(tenant_id) -> None:
    """Serialise appends to one tenant's chain, outside the supported path.

    ``select_for_update`` locks the rows it finds, so once a tenant has
    events concurrent appends queue behind the head row and cannot both read
    the same ``prev_hash``. A tenant with *no* events yet has no row to lock:
    two concurrent first writes would both see an empty chain, both hash
    against "" and write two rows each claiming to be the head, which verify
    then reports as tampering on rows nothing touched.

    A transaction-scoped advisory lock closes that gap. PostgreSQL only —
    SQLite has no advisory locks and the fast suite must keep running without
    them — mirroring how ``common.tenant.supports_tenant_guc`` gates the
    tenant session settings on the vendor. It must be taken inside a
    transaction, which :func:`append_event` guarantees.
    """
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_chain_lock_key(tenant_id)])


def _chain_lock_key(tenant_id) -> int:
    """A stable bigint from the tenant id, for the advisory lock.

    Derived from a sha256 of the canonical tenant id rather than
    :func:`hash`, which is salted per process and would give two workers
    different locks for the same tenant. A collision merely shares a lock,
    costing serialisation between two tenants and never correctness.

    The digest is truncated to **15 hex digits (60 bits), not a full 16**:
    ``int(digest[:16], 16)`` is an unsigned 64-bit value and exceeds
    ``2**63`` for about half of all tenant ids (49.92% of 200,000 measured
    uuid4s), while ``pg_advisory_xact_lock`` takes a signed ``bigint``.
    psycopg3 routes an int at or above ``2**63`` to the numeric dumper,
    PostgreSQL then fails function resolution, and ``append_event`` raises
    inside its atomic block — a 500 on every audited write for that tenant.
    Sixty bits keeps distinct tenants on distinct locks in practice (a
    collision costs only serialisation) while staying inside signed bigint
    range for every input.
    """
    digest = hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def append_event(*, tenant_id, **fields) -> AuditEvent:
    """Append one chained audit event and return it (AUD-002).

    ``hash_chain`` is :func:`chain_digest` over the tenant's previous hash
    and the canonical form of the chained fields. Every field the writers
    pass is in the digest, so an in-place ``UPDATE`` of any of them leaves
    the stored hash unreproducible — which is what :func:`verify_chain`
    detects and reports.

    The chain is **per tenant and strictly ordered**. The previous-hash
    lookup is filtered by ``tenant_id``, so each tenant's chain commits only
    to its own rows and interleaved writes across tenants never cross-link.
    That is Review Focus #4: a shared cursor would chain one hospital's
    event onto another's hash and report tampering on rows nothing touched.

    Concurrency: the head is fetched with ``select_for_update`` inside this
    function's own ``transaction.atomic()``. On PostgreSQL a row lock is held
    to the end of the *enclosing* transaction — ``ATOMIC_REQUESTS`` makes
    that the request — so two concurrent appends for one tenant serialise
    instead of both reading the same head. The ``atomic()`` is required, not
    tidy: evaluated outside a transaction the ``FOR UPDATE`` lookup raises
    ``TransactionManagementError`` on PostgreSQL, and on SQLite it is a
    silent no-op, so either way the ordering guarantee would be lost.
    (Django documents this in ``ref/models/querysets``: on a backend without
    ``SELECT ... FOR UPDATE`` support, ``select_for_update`` has no effect
    and raises no error.) ``transaction.atomic()`` nests, so under
    ``ATOMIC_REQUESTS`` this joins the request's transaction as a savepoint
    rather than opening a second one.

    No PHI is accepted. The field set is identifiers, the action, and the
    provenance markers; callers must never pass demographics, names, or free
    text beyond the break-glass ``reason``.
    """
    key = _hmac_key()
    canonical = _canonical_fields(fields)
    with transaction.atomic():
        _lock_tenant_chain(tenant_id)
        previous = (
            AuditEvent.objects.filter(tenant_id=tenant_id)
            .order_by("-occurred_at", "-id")
            .select_for_update()
            .first()
        )
        # A tenant with no events yet has no head; the empty string is the
        # chain's origin, matching the column's default for pre-chain rows.
        prev_hash = previous.hash_chain if previous else ""
        digest = chain_digest(key, prev_hash, canonical)
        return AuditEvent.objects.create(
            **fields, tenant_id=tenant_id, hash_chain=digest
        )


def verify_chain(*, tenant_id) -> dict:
    """Recompute one tenant's audit chain and report the first failure.

    Returns exactly ``{"valid": bool, "checked": int, "first_bad": <id>|None}``:

    * ``valid`` — every chained row recomputed to its stored hash;
    * ``checked`` — the number of chained rows whose digest was recomputed and
      compared, the anchor row included. A row whose comparison failed is
      counted too, because it was checked and found wanting;
    * ``first_bad`` — the id of the earliest mismatch, or ``None``.

    Rows carrying the column's empty default are pre-chain rows: they are
    skipped without being counted or reported, because a row written before
    the chain existed is not evidence of tampering, and they contribute their
    empty stored hash as the next row's ``prev_hash``.

    AUD-004 interaction: the walk **re-anchors on the oldest surviving
    chained row**, accepting its stored hash instead of recomputing it
    against a predecessor a retention purge may legitimately have deleted.
    The concession is made once, for the oldest row only, so a hole punched
    anywhere later still fails at the row that follows it. What the chain
    consequently cannot prove is that nothing was *ever* deleted — that needs
    an anchor outside the table (see :func:`purge_expired`).
    """
    key = _hmac_key()
    prev_hash = ""
    anchored = False
    checked = 0
    first_bad = None
    for event in (
        AuditEvent.objects.filter(tenant_id=tenant_id)
        .order_by("occurred_at", "id")
        .iterator()
    ):
        if not event.hash_chain:
            # Pre-chain row (AUD-002 shipped after some deployments already
            # had rows). SKIPPED, not reported: its stored hash is the empty
            # string, which is what the next row commits to.
            prev_hash = ""
            continue
        checked += 1
        if not anchored:
            # The oldest surviving chained row anchors the walk. Its
            # predecessor is either nothing at all (this is the tenant's
            # first event, or only pre-chain rows precede it) or a row a
            # retention purge legitimately deleted. Neither can be
            # recomputed, so the row's own stored hash is the base of the
            # chain for this database.
            anchored = True
            prev_hash = event.hash_chain
            continue
        if chain_digest(key, prev_hash, _canonical_fields(event)) != event.hash_chain:
            # ``==`` rather than ``hmac.compare_digest``: both sides are
            # locally computed digests of public, self-derived data, and the
            # comparison is not an authentication gate against a remote
            # attacker who could time individual attempts. The chain's
            # protection is that the key is never in the database, so an
            # attacker who can UPDATE a row still cannot compute a digest
            # that matches it without the key.
            first_bad = str(event.id)
            break
        prev_hash = event.hash_chain
    return {"valid": first_bad is None, "checked": checked, "first_bad": first_bad}


def purge_expired(*, tenant_id, retention_days: int | None = None) -> int:
    """Delete this tenant's audit events older than ``retention_days`` (AUD-004).

    Returns the number of rows deleted. The cutoff is a strict ``<`` against
    ``timezone.now() - timedelta(days=retention_days)``, so a row landing
    exactly on the boundary survives. Only this tenant's rows are considered:
    one hospital's retention policy must not delete another's evidence.

    When ``retention_days`` is omitted it resolves to
    ``settings.AUDIT_RETENTION_DAYS`` — the env-overridable, default-365
    placeholder documented in ``base.py`` (OQ-08 still open with the
    customer). Resolving it here rather than at every call site is what stops
    a scheduled job (Task 23) from quietly running with a different window
    than the operator configured simply because no value was passed.

    The purge **only ever deletes**. It does not rewrite the surviving rows'
    ``hash_chain``, because an audit store that edits its own rows is not
    append-only and the chain would be attesting to hashes the purge itself
    wrote after the fact. A purged row's hash is therefore simply gone, and
    :func:`verify_chain` accounts for it by re-anchoring on the oldest
    surviving chained row: **a purge trims the chain rather than breaking
    it.** That is the retention semantics of AUD-004 — a verified trail of
    the rows the policy still keeps, rather than a chain that reports
    tampering because a scheduled job did its job.

    The cost is honest and worth stating: the chain cannot detect wholesale
    removal, only mutation and selective deletion. An attacker with direct
    database access can drop rows wholesale and the re-anchored chain will
    happily verify what remains; a hole punched anywhere but the head still
    fails at the row that follows it. Proving absence needs an anchor outside
    the table — an append-only export or a countersignature — which is out of
    scope for R1.
    """
    if retention_days is None:
        retention_days = settings.AUDIT_RETENTION_DAYS
    cutoff = timezone.now() - timedelta(days=retention_days)
    with transaction.atomic():
        deleted, _ = (
            AuditEvent.objects.filter(tenant_id=tenant_id, occurred_at__lt=cutoff)
            .delete()
        )
    return deleted


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

    append_event(
        tenant_id=tenant_id,
        user_id=request.user.pk if request.user.is_authenticated else None,
        action="read",
        entity_type=instance._meta.db_table,
        entity_id=str(instance.pk),
        source_ip=request.META.get("REMOTE_ADDR"),
    )
