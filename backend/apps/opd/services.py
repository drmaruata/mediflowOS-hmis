"""OPD services — token series allocation (REG-010, ABD-010)."""
import uuid

from django.db import IntegrityError, OperationalError, transaction

from .models import TokenSeries

#: Same bounded-retry discipline as ``patient_registry.services.generate_uhid``.
MAX_RETRIES = 3

#: Fallback prefix when a department carries no machine code (none do today)
#: or the registration names no intake department at all.
GEN_PREFIX = "GEN"


def _default_prefix(*, tenant_id: uuid.UUID, department_id) -> str:
    """Series prefix for a department, defaulting to GEN.

    The lookup is tenant-scoped: a department id from another hospital must
    not decide this tenant's token naming.
    """
    if department_id is None:
        return GEN_PREFIX
    from apps.identity_tenancy.models import Department

    department = Department.objects.filter(
        tenant_id=tenant_id, id=department_id
    ).first()
    # Department has no machine ``code`` field yet; getattr keeps the future
    # additive column from changing this call site.
    return getattr(department, "code", None) or GEN_PREFIX


def next_token_number(
    *, tenant_id: uuid.UUID, facility_id: uuid.UUID, department_id
) -> tuple[str, int]:
    """Return the next OPD token ``(series, number)`` for a department.

    ``department_id`` is null for a registration with no intake department,
    which keys a shared GEN series for the facility. Same locking discipline
    as :func:`patient_registry.services.generate_uhid`: the series row is
    locked inside an explicit atomic block, and a lost first-create race is
    retried. ``order_by("created_at").first()`` makes the earliest-created row
    canonical, so a retry deterministically re-reads the winner.

    The caller creates the ``opd.Token`` row itself after this returns; both
    stay in the same request transaction (ATOMIC_REQUESTS), so a reserved
    number cannot be lost to a later failure.

    The returned series is the *stored* prefix of the series row: a
    pre-configured TokenSeries (say ``MED``) is authoritative, and the
    department-derived default only applies when the service creates the row.
    A retry re-reads the winner's row, so concurrent callers agree on both the
    series name and the number.
    """
    for _ in range(MAX_RETRIES):
        try:
            with transaction.atomic():
                series = (
                    TokenSeries.objects.select_for_update()
                    .filter(
                        tenant_id=tenant_id,
                        facility_id=facility_id,
                        department_id=department_id,
                    )
                    .order_by("created_at")
                    .first()
                )
                if series is None:
                    series = TokenSeries.objects.create(
                        tenant_id=tenant_id,
                        facility_id=facility_id,
                        department_id=department_id,
                        prefix=_default_prefix(
                            tenant_id=tenant_id, department_id=department_id
                        ),
                        next_number=1,
                    )
                prefix = series.prefix
                number = series.next_number
                series.next_number = number + 1
                series.save(update_fields=["next_number"])
        except IntegrityError:
            continue
        except OperationalError as exc:
            # SQLite's lock-upgrade deadlock (see generate_uhid): the loser
            # gets ``database is locked`` immediately rather than after the
            # busy timeout. The winner commits microseconds later; retry and
            # read its row deterministically via ``order_by("created_at")``.
            if "locked" not in str(exc):
                raise
            continue
        return prefix, number
    raise RuntimeError("Could not allocate an OPD token number after retries")
