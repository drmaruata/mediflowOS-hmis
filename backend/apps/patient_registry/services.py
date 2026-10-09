"""Patient registry services — server-issued identifiers (REG-001) and probable-duplicate detection (REG-003)."""
import re
import uuid

from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from common.crypto import search_index
from .models import Patient, PatientSequence, field_keys
from .validation import MOBILE_RE, normalise_mobile

#: Bounded retries for the first-create race. Each retry runs in a fresh
#: savepoint (``transaction.atomic()`` per attempt), so the bound keeps a
#: pathological lock/retry cascade from stretching a single registration.
MAX_RETRIES = 3

#: The UHID period is the calendar month of registration, e.g. ``2026-10``.
PERIOD_FORMAT = "%Y-%m"

#: Birth-data keys under which a patient's year of birth may be stored in
#: ``demographics``. ``yearOfBirth`` is the established key (the ABDM gateway
#: and every existing registry row use it); ``dob``/``age_years`` are the keys
#: the registration contract accepts (REG-007). Reading all of them lets a
#: candidate match a patient whichever producer wrote the row.
_DOB_KEYS = ("dob", "dateOfBirth", "date_of_birth")
_YEAR_KEYS = ("yearOfBirth", "year_of_birth", "yob")
_AGE_KEYS = ("age_years", "age")
_MOBILE_KEY = "mobile"

#: Safety bound on the rows a single duplicate probe pulls back. ``icontains``
#: is an inexact prefilter refined in Python; without a bound a common name in
#: a large tenant would drag the whole registry through the request.
_MAX_SCAN = 200


def _normalise_name(value) -> str:
    """Casefold and collapse whitespace: ``" John  DOE "`` -> ``"john doe"``.

    A duplicate is a *person*, not a spelling; the match must survive capital
    and spacing differences that carry no identity information.
    """
    return " ".join(str(value or "").split()).casefold()


def birth_year(record: dict) -> int | None:
    """The year of birth implied by a demographics/contact mapping, if any.

    ``dob`` may be an ISO date or a bare year; ``age_years`` is converted using
    the current year. Returns ``None`` when no usable key is present, so a
    name-only candidate can never match on a guess.
    """
    record = record or {}
    for key in _DOB_KEYS:
        match = re.search(r"(\d{4})", str(record.get(key) or ""))
        if match:
            return int(match.group(1))
    for key in _YEAR_KEYS:
        value = record.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    for key in _AGE_KEYS:
        value = record.get(key)
        if value not in (None, ""):
            try:
                return timezone.now().year - int(value)
            except (TypeError, ValueError):
                continue
    return None


def _mobile_of(patient: Patient) -> str:
    return normalise_mobile((patient.contact or {}).get(_MOBILE_KEY))


def _match_by_mobile(tenant_queryset, mobile: str):
    """Tenant-scoped mobile matches, routed through the HMAC index (REG-008).

    The database prefilter is now an exact-digest match on the keyed-HMAC
    ``mobile_idx`` column: ``contact.mobile`` is ciphertext, so the pre-REG-008
    JSON substring lookup (``json_extract``/``->>``) has nothing to scan. The
    probe is canonicalised exactly like the write path (``normalise_mobile`` in
    both the field sealer and :func:`find_duplicates`), so ``+91``/spacing in
    the candidate cannot evade the digest. The Python
    ``normalise_mobile`` comparison then confirms as defence-in-depth, and
    ``_MAX_SCAN`` still bounds the refinement loop.
    """
    canonical = normalise_mobile(mobile)
    _, hmac_key = field_keys()
    candidates = tenant_queryset.filter(
        mobile_idx=search_index(canonical, key=hmac_key)
    )
    for patient in candidates[:_MAX_SCAN]:
        if _mobile_of(patient) == mobile:
            yield patient


def _match_by_name_and_birth(tenant_queryset, name: str, year: int):
    """Tenant-scoped ``normalised name + year of birth`` matches.

    The database narrows on the longest name token (a portable, case-insensitive
    JSON key substring lookup — ``json_extract`` on SQLite, ``->>`` on
    PostgreSQL), then the exact casefolded comparison and birth-year equality
    are applied in Python. Prefiltering on the whole normalised name would miss
    ``"John  Doe"`` because of its internal whitespace; the token prefilter is
    deliberately loose and the Python check is what decides.
    """
    tokens = name.split()
    token = max(tokens, key=len) if tokens else name
    candidates = tenant_queryset.filter(demographics__name__icontains=token)
    for patient in candidates[:_MAX_SCAN]:
        demographics = patient.demographics or {}
        if _normalise_name(demographics.get("name")) != name:
            continue
        if birth_year(demographics) == year:
            yield patient


def find_duplicates(*, tenant_id, candidate: dict, limit: int = 5) -> list[Patient]:
    """Ranked probable duplicates for ``candidate`` within one tenant (REG-003).

    Precedence, strongest identifier first: an exact ABHA number, then a
    normalised name with a matching year of birth, then a normalised mobile.
    The queryset is tenant-scoped from the first filter, so a candidate can
    never surface another hospital's patient, and ``limit`` bounds the
    response. No candidate and no match ever leaves the tenant.
    """
    if not tenant_id:
        return []

    candidate = candidate or {}
    abha = str(candidate.get("abha_number") or "").strip()
    name = _normalise_name(candidate.get("name"))
    mobile = normalise_mobile(candidate.get("mobile"))
    year = birth_year(candidate)

    base = Patient.objects.filter(tenant_id=tenant_id)
    ranked: dict = {}

    # 1. Exact ABHA — the strongest identifier; the caller-supplied number is
    #    already known to them, so matching it is not an information leak.
    #    REG-008: the probe goes through the keyed ``abha_number_idx`` digest
    #    (``filter_by_abha``), never through the ciphertext column.
    if abha:
        for patient in Patient.objects.filter_by_abha(tenant_id, abha):
            ranked[patient.id] = (0, patient)

    # 2. Name AND a birth year. Name alone is too weak to warn on.
    if name and year is not None:
        for patient in _match_by_name_and_birth(base, name, year):
            ranked.setdefault(patient.id, (1, patient))

    # 3. Mobile, but only when the candidate itself carries a valid one.
    if mobile and MOBILE_RE.fullmatch(mobile):
        for patient in _match_by_mobile(base, mobile):
            ranked.setdefault(patient.id, (2, patient))

    ordered = sorted(ranked.values(), key=lambda item: (item[0], str(item[1].id)))
    return [patient for _, patient in ordered[:limit]]


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
