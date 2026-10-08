"""CSV import/export for configuration rows (SET-013).

``GET .../export/`` renders the tenant's beds or staff positions as a CSV
document; ``POST .../import/`` ingests one. Both use the stdlib ``csv`` module
only — no new dependency (AGENTS.md dependency rules). The column sets are the
API contract, and they are symmetric: export writes exactly
:data:`BED_COLUMNS`/:data:`STAFF_POSITION_COLUMNS` as the header row, and
import refuses any file whose header row is not exactly that set as a 422
(``CsvImportError``) before a single row is inspected.

Import is all-or-nothing per request. Every row is validated against the
resource serializer *and* the tenant-scoped ward/department table before any
write; if even one row fails, the response carries that row in ``errors`` and
no row is written. Only a fully valid file enters the explicit
``transaction.atomic()`` block, because ``ATOMIC_REQUESTS`` is False in the
test profile and the atomicity must live in code, not middleware
(AGENTS.md on explicit transactions). The update/create decision uses a
natural key per tenant — ``(ward, bed_number)`` for beds and
``(department, designation)`` for staff positions — so re-importing an export
updates in place rather than duplicating rows, and a name that belongs to
another hospital resolves to nothing and errors.

Import writes carry the same history as the config viewsets (SET-010,
SET-012): every updated row archives its pre-update state into
``ConfigRevision`` via :func:`apps.identity_tenancy.services.record_revision`
before the new values land — a bulk load must never silently erase the window
a locked indicator period re-reads — and every written row, created or
updated, lands one ``AuditEvent`` whose ``entity_type`` is the model's
``db_table``, matching ``TenantScopedQuerysetMixin``'s shape. Created rows mint
no revision, exactly like the viewsets. The natural key must also be unique
*within a file*: the model has only an index, not a constraint, so a repeated
``(ward, bed_number)`` or ``(department, designation)`` is rejected as a row
error and the whole file writes nothing.
"""
import csv
import io

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.exceptions import APIException

from .models import Bed, Department, StaffPosition, Ward
from .serializers import BedSerializer, StaffPositionSerializer
from .services import record_revision

#: Fixed export/import columns for beds (SET-013). ``ward`` is the ward's
#: *name* — a human-readable token the import resolves back within the tenant.
BED_COLUMNS = ["ward", "bed_number", "functional", "active"]

#: Derived export/import columns for staff positions (SET-013). The model has
#: no ``active`` field (Task 8 added it only to ``Bed``), so the export must
#: not invent one; the department is carried as its name, like beds carry ward.
STAFF_POSITION_COLUMNS = [
    "department",
    "designation",
    "specialty",
    "sanctioned",
    "in_position",
]


class CsvImportError(APIException):
    """The upload is not a well-formed CSV document for this resource.

    HTTP 422 Unprocessable Content: the request was understood but the file
    body cannot be treated as an import document — undecodable bytes, or a
    header row that does not match the resource's fixed column set. Raised
    before any row is inspected so a malformed upload can never silently
    import a subset. DRF answers APIException subclasses with the declared
    status automatically, which is how the repo gets 422 semantics rather
    than ``ValidationError``'s 400 (AGENTS.md: return 422-class deliberately).
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "The uploaded file is not a valid CSV document."
    default_code = "unprocessable_entity"


class CsvImportFileSerializer(serializers.Serializer):
    """multipart upload wrapper: the CSV document under ``file`` (SET-013)."""

    file = serializers.FileField()


class CsvImportResultSerializer(serializers.Serializer):
    """One import's counts and per-row errors, as documented for SET-013."""

    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.DictField(), default=list)


def render_beds_csv(queryset) -> str:
    """Render tenant-scoped beds as CSV text (SET-013).

    The header row is exactly :data:`BED_COLUMNS`; booleans are lowercase
    ``true``/``false`` so the round trip through DRF's ``BooleanField`` stays
    lossless, and the caller's ordering is preserved so exports are
    deterministic and diffable.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=BED_COLUMNS)
    writer.writeheader()
    for bed in queryset:
        writer.writerow(
            {
                "ward": bed.ward.name,
                "bed_number": bed.bed_number,
                "functional": "true" if bed.functional else "false",
                "active": "true" if bed.active else "false",
            }
        )
    return buffer.getvalue()


def render_staff_positions_csv(queryset) -> str:
    """Render tenant-scoped staff positions as CSV text (SET-013).

    Same discipline as :func:`render_beds_csv`: header exactly
    :data:`STAFF_POSITION_COLUMNS`, integers as plain decimal strings, and the
    nullable ``specialty`` as an empty cell rather than the string ``None`` so
    an import round trip stores the model's blank value, not the literal.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=STAFF_POSITION_COLUMNS)
    writer.writeheader()
    for position in queryset:
        writer.writerow(
            {
                "department": position.department.name,
                "designation": position.designation,
                "specialty": position.specialty or "",
                "sanctioned": str(position.sanctioned),
                "in_position": str(position.in_position),
            }
        )
    return buffer.getvalue()


def parse_rows(file_obj, columns) -> list:
    """Read an uploaded CSV into data rows, or raise :class:`CsvImportError`.

    A file whose bytes are not UTF-8 — or whose header row is not exactly
    ``columns`` — is refused as a 422 before any row is inspected: the
    document is malformed, which is a different failure than a row that fails
    validation, and must never silently import a subset. ``utf-8-sig`` absorbs
    a byte-order mark some spreadsheet exports prepend.
    """
    try:
        text = file_obj.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvImportError("The uploaded file is not UTF-8 encoded.")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    missing = [column for column in columns if column not in headers]
    extra = [column for column in headers if column not in columns]
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"missing columns: {', '.join(missing)}")
        if extra:
            detail.append(f"unknown columns: {', '.join(extra)}")
        raise CsvImportError("; ".join(detail))
    return list(reader)


def _row_reason(serializer) -> str:
    """One-line reason from a serializer's ``.errors`` dict (SET-013).

    The same message DRF would answer a 400 with, flattened so it fits one
    cell of the import response's ``errors`` list.
    """
    return "; ".join(
        f"{field}: {message}"
        for field, messages in serializer.errors.items()
        for message in messages
    )


def _resolve_exactly_one(matches_by_name, name, label, index, errors):
    """Resolve ``name`` to the caller's one matching row, else a row error.

    ``matches_by_name`` maps each distinct name seen in the file to the
    caller's rows sharing it; the caller builds it with ONE tenant-scoped
    query, so the resolution never fans out a lookup per CSV row. A name that
    exists only in another hospital resolves to nothing here and lands in
    ``errors`` instead of a cross-tenant write — the isolation guarantee the
    brief pins. Ambiguity within the tenant (two rows sharing a name) is also
    an error: silently picking one could move a bed or position under the
    wrong row, which is no better than a guess.
    """
    if not name:
        errors.append({"row": index, "reason": f"{label} is required."})
        return None
    matches = matches_by_name.get(name, [])
    if not matches:
        errors.append(
            {
                "row": index,
                "reason": f"{label} '{name}' does not exist in this tenant.",
            }
        )
        return None
    if len(matches) > 1:
        errors.append(
            {
                "row": index,
                "reason": f"{label} name '{name}' is ambiguous: matches {len(matches)} rows.",
            }
        )
        return None
    return matches[0]


def _claim_natural_key(claimed, key, index, errors, natural_key_label) -> bool:
    """Refuse a natural key that repeats an earlier row of the same file.

    The model has only an index on the natural key, not a unique constraint,
    so without this check two rows for the same ``(ward, bed_number)`` would
    both plan a create and double-write. A repeat is an explicit row error
    rather than a silent duplicate; because one error aborts the file
    (all-or-nothing), nothing is written either way. Round-trip exports are
    naturally unique, so a re-imported export can never trip this.
    """
    if key in claimed:
        errors.append(
            {
                "row": index,
                "reason": (
                    f"duplicate row: {natural_key_label} already appears "
                    "earlier in this file."
                ),
            }
        )
        return False
    claimed.add(key)
    return True


def _write_audit_event(tenant_id, instance, action, user) -> None:
    """One ``AuditEvent`` per import-written row, mirroring the tenant mixin (SET-012).

    ``TenantScopedQuerysetMixin._write_audit_log`` records ``entity_type`` as
    the model's ``db_table`` and ``entity_id`` as the stringified pk; this
    helper writes the same shape so an admin screen filtering the trail by
    entity sees import-driven changes exactly where it sees PATCH/POST ones.
    The helper deliberately omits the source IP and break-glass reason the
    mixin also records: those live on the request, which the bulk file layer
    does not carry. The import passes the acting ``request.user``, so the
    event is attributed to the same account the mixin would have used.
    """
    from apps.audit.models import AuditEvent

    user_id = user.pk if getattr(user, "is_authenticated", False) else None
    AuditEvent.objects.create(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        entity_type=instance._meta.db_table,
        entity_id=str(instance.pk),
    )


def import_beds(tenant_id, rows, user) -> dict:
    """Validate every bed row, then write all of them atomically (SET-013).

    Returns ``{"created": n, "updated": m, "errors": [{"row", "reason"}]}``.
    A row is "an update" when its ``(ward, bed_number)`` natural key already
    exists in the tenant; otherwise it is a create. Any row error — validation
    failure, unknown ward, or a natural key repeated within the file — aborts
    the whole request with zero writes; only an all-valid file enters the
    atomic block. Wards are resolved once per distinct name in the file rather
    than per row, so the tenant-scoped lookup cannot fan out a query per CSV
    row.

    Writes carry the config history contract (SET-010, SET-012): each update
    first archives the row's pre-update state via ``record_revision`` — the
    instance still holds the committed values here, exactly as
    ``EffectiveDatedConfigMixin.perform_update`` relies on — and every written
    row, created or updated, lands one ``AuditEvent``. ``user`` is the acting
    account, used to attribute both trails.
    """
    ward_names = {row["ward"] for row in rows if row["ward"]}
    wards_by_name = {}
    for ward in Ward.objects.filter(tenant_id=tenant_id, name__in=ward_names):
        wards_by_name.setdefault(ward.name, []).append(ward)

    claimed = set()
    plans = []
    errors = []
    for index, row in enumerate(rows, start=1):
        ward = _resolve_exactly_one(
            wards_by_name, row["ward"], "ward", index, errors
        )
        if ward is None:
            continue
        if not _claim_natural_key(
            claimed,
            (ward.id, row["bed_number"]),
            index,
            errors,
            f"ward '{ward.name}', bed_number '{row['bed_number']}'",
        ):
            continue
        data = {
            "ward": ward.id,
            "bed_number": row["bed_number"],
            "functional": row["functional"],
            "active": row["active"],
        }
        existing = Bed.objects.filter(
            tenant_id=tenant_id, ward=ward, bed_number=row["bed_number"]
        ).first()
        serializer = (
            BedSerializer(existing, data=data) if existing else BedSerializer(data=data)
        )
        if not serializer.is_valid():
            errors.append({"row": index, "reason": _row_reason(serializer)})
            continue
        plans.append((index, "update" if existing else "create", serializer))

    if errors:
        return {"created": 0, "updated": 0, "errors": errors}

    created = updated = 0
    with transaction.atomic():
        for _index, action, serializer in plans:
            if action == "create":
                serializer.save(tenant_id=tenant_id)
                _write_audit_event(tenant_id, serializer.instance, "create", user)
                created += 1
            else:
                # SET-010: archive the pre-update state before the new values
                # land — serializer.instance still holds the committed row.
                record_revision(serializer.instance, user)
                serializer.save()
                _write_audit_event(tenant_id, serializer.instance, "update", user)
                updated += 1
    return {"created": created, "updated": updated, "errors": []}


def import_staff_positions(tenant_id, rows, user) -> dict:
    """Validate every staff-position row, then write all atomically (SET-013).

    Same contract as :func:`import_beds`, keyed on the model's
    ``(tenant_id, department, designation)`` index: a position whose
    ``(department, designation)`` natural key already exists is updated,
    otherwise created. Departments resolve exactly like wards — within the
    caller's tenant, with unknown and ambiguous names both refused, and a
    natural key repeated within the file refused as a duplicate row — so a
    duplicated position can never double-create.

    The history contract mirrors :func:`import_beds`: updates archive their
    pre-update state into ``ConfigRevision`` (SET-010) and every written row
    lands one ``AuditEvent`` (SET-012), both attributed to ``user``.
    """
    department_names = {
        row["department"] for row in rows if row["department"]
    }
    departments_by_name = {}
    for department in Department.objects.filter(
        tenant_id=tenant_id, name__in=department_names
    ):
        departments_by_name.setdefault(department.name, []).append(department)

    claimed = set()
    plans = []
    errors = []
    for index, row in enumerate(rows, start=1):
        department = _resolve_exactly_one(
            departments_by_name,
            row["department"],
            "department",
            index,
            errors,
        )
        if department is None:
            continue
        if not _claim_natural_key(
            claimed,
            (department.id, row["designation"]),
            index,
            errors,
            f"department '{department.name}', designation '{row['designation']}'",
        ):
            continue
        data = {
            "department": department.id,
            "designation": row["designation"],
            "specialty": row["specialty"],
            "sanctioned": row["sanctioned"],
            "in_position": row["in_position"],
        }
        existing = StaffPosition.objects.filter(
            tenant_id=tenant_id, department=department, designation=row["designation"]
        ).first()
        serializer = (
            StaffPositionSerializer(existing, data=data)
            if existing
            else StaffPositionSerializer(data=data)
        )
        if not serializer.is_valid():
            errors.append({"row": index, "reason": _row_reason(serializer)})
            continue
        plans.append((index, "update" if existing else "create", serializer))

    if errors:
        return {"created": 0, "updated": 0, "errors": errors}

    created = updated = 0
    with transaction.atomic():
        for _index, action, serializer in plans:
            if action == "create":
                serializer.save(tenant_id=tenant_id)
                _write_audit_event(tenant_id, serializer.instance, "create", user)
                created += 1
            else:
                # SET-010: archive the pre-update state before the new values
                # land — serializer.instance still holds the committed row.
                record_revision(serializer.instance, user)
                serializer.save()
                _write_audit_event(tenant_id, serializer.instance, "update", user)
                updated += 1
    return {"created": created, "updated": updated, "errors": []}
