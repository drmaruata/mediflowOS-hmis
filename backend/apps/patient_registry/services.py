"""Patient registry services — server-issued identifiers (REG-001)."""
import uuid

from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from .models import PatientSequence

#: Bounded retries for the first-create race. Each retry runs in a fresh
#: savepoint (``transaction.atomic()`` per attempt), so the bound keeps a
#: pathological lock/retry cascade from stretching a single registration.
MAX_RETRIES = 3

#: The UHID period is the calendar month of registration, e.g. ``2026-10``.
PERIOD_FORMAT = "%Y-%m"


def _current_period() -> str:
    return timezone.now().strftime(PERIOD_FORMAT)


def generate_uhid(*, tenant_id: uuid.UUID) -> str:
    """Mint the next UHID for ``tenant_id``: ``UHID-<YYYY><MM>-<000001>``.

    The identifier is server-owned: callers (the registration view, inside the
    request transaction) never let the client choose it, and the per-tenant,
    per-month sequence row guarantees two registrations for the same tenant and
    month cannot collide on a number.

    Locking follows AGENTS §4: the sequence row is locked with
    ``select_for_update`` inside an explicit ``transaction.atomic()``, because
    the tenant context binding is only valid inside a transaction — this call
    must stay in the view path, never in a Celery task without its own tenant
    block. On PostgreSQL the lock serialises concurrent first-time calls; on
    SQLite, where ``select_for_update`` is a documented no-op, the loser hits
    the unique constraint and the bounded retry re-reads the winner's
    committed row.
    """
    for _ in range(MAX_RETRIES):
        try:
            with transaction.atomic():
                period = _current_period()
                sequence = (
                    PatientSequence.objects.select_for_update()
                    .filter(tenant_id=tenant_id, kind="uhid", period=period)
                    .first()
                )
                if sequence is None:
                    sequence = PatientSequence.objects.create(
                        tenant_id=tenant_id, kind="uhid", period=period, next_value=1
                    )
                next_value = sequence.next_value
                sequence.next_value = next_value + 1
                sequence.save(update_fields=["next_value"])
        except IntegrityError:
            # The first-create race: another transaction committed the same
            # (tenant, kind, period) row first. Re-read it on the next attempt.
            continue
        except OperationalError as exc:
            # SQLite's lock-upgrade deadlock (see module docstring): the loser
            # gets ``database is locked`` immediately rather than after the
            # busy timeout. The winner commits microseconds later; retry and
            # read its row.
            if "locked" not in str(exc):
                raise
            continue
        # ``:06d`` zero-pads to six digits, a stated interface (REG-001,
        # ``UHID-YYYYMM-NNNNNN``); past 999,999 UHIDs in one tenant-month the
        # field widens rather than wrapping. Guarding that ceiling is a product
        # decision, so the format is documented here, not enforced.
        return f"UHID-{period.replace('-', '')}-{next_value:06d}"
    raise RuntimeError("Could not allocate a UHID after retries")
