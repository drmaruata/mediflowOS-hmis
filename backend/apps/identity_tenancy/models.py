"""Identity, tenancy and administration models (TEN-001 to TEN-011, SET-001 to SET-012)."""
import uuid

from django.conf import settings
from django.db import models


class Tenant(models.Model):
    """The tenant root.

    This is the one domain model that has no ``tenant_id``: it *is* the
    tenancy. Every other tenant-owned model carries one, including models that
    are otherwise reachable from here by a foreign key chain.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    tier = models.CharField(max_length=32, default="standard")
    accreditation_profile = models.JSONField(default=list)  # e.g. ["NQAS-DH","NABH-6"]
    db_mode = models.CharField(max_length=16, default="shared")  # shared | dedicated
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "identity.tenant"


class Facility(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="facilities", db_index=True)
    name = models.CharField(max_length=200)
    level = models.CharField(max_length=64)  # District Hospital, CHC, PHC...
    abdm_hip_id = models.CharField(max_length=64, null=True, blank=True)
    abdm_facility_id = models.CharField(max_length=64, null=True, blank=True)
    hfr_id = models.CharField(max_length=64, null=True, blank=True)
    abdm_registration_status = models.CharField(max_length=32, default="pending")
    address = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "identity.facility"


class Department(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="departments", db_index=True)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="departments", db_index=True)
    name = models.CharField(max_length=120)
    opd_enabled = models.BooleanField(default=False)
    ipd_enabled = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "identity.department"


class Ward(models.Model):
    """Tenancy is denormalised onto every tenant-owned row.

    Ward is reachable from Tenant through Department and Facility, but RLS
    policies cannot join: a policy may only reference columns of its own table
    plus expressions, and a subquery into another RLS-protected table would be
    subject to that table's own policies. Carrying tenant_id directly is what
    makes `tenant_id = current_setting('app.tenant_id')::uuid` expressible.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="wards", db_index=True)
    name = models.CharField(max_length=120)
    type_tag = models.CharField(max_length=64)  # Medical, Surgical, Maternity, Paediatric, ICU, SNCU, NRC
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "identity.ward"
        indexes = [models.Index(fields=["tenant_id", "department", "active"])]


class Bed(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name="beds", db_index=True)
    bed_number = models.CharField(max_length=32)
    functional = models.BooleanField(default=True)
    occupied = models.BooleanField(default=False)
    #: Additive (SET-011): a bed is deactivated, never deleted, so its history
    #: and any locked indicator period keep pointing at the same row. Unlike
    #: ``functional`` — the bed's equipment/operational state — ``active`` is
    #: the administrative lifecycle flag the configuration surface flips.
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "identity.bed"
        indexes = [models.Index(fields=["tenant_id", "ward", "functional"])]


class ServiceUnit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="service_units", db_index=True)
    name = models.CharField(max_length=120)
    type_tag = models.CharField(max_length=64)  # OT, Labour Room, Laboratory, Radiology, Pharmacy, Blood Bank, Mortuary, CSSD

    class Meta:
        db_table = "identity.service_unit"
        indexes = [models.Index(fields=["tenant_id", "facility", "type_tag"])]


class StaffPosition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="staff_positions", db_index=True)
    designation = models.CharField(max_length=120)
    specialty = models.CharField(max_length=120, null=True, blank=True)
    sanctioned = models.IntegerField(default=0)
    in_position = models.IntegerField(default=0)

    class Meta:
        db_table = "identity.staff_position"
        indexes = [models.Index(fields=["tenant_id", "department", "designation"])]


class Role(models.Model):
    """A named bundle of permissions (TEN-004).

    ``tenant`` is null for platform-wide roles, which apply across tenants -
    used by the platform administrator who onboards tenants (TEN-010). A tenant
    role belongs to exactly one hospital.

    Roles are data rather than Django groups because permissions here are
    facility- and department-scoped (TEN-005), which a flat group cannot express.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, null=True, blank=True, related_name="roles",
        db_index=True,
    )
    name = models.CharField(max_length=64)
    #: IRI-style permission strings, e.g. "patient_registry.view_patient".
    permissions = models.JSONField(default=list)
    #: TEN-006: privileged roles must present a second factor.
    require_mfa = models.BooleanField(default=False)
    #: TEN-007: this role may be used to reach records outside its own scope,
    #: but only with a recorded reason.
    allows_break_glass = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "identity.role"
        unique_together = [["tenant", "name"]]
        indexes = [models.Index(fields=["tenant", "name"])]


class UserMembership(models.Model):
    """Links an account to a tenant with a role (TEN-004).

    Django's own ``auth.User`` is deliberately reused rather than replaced: it
    keeps the admin site, ``django-otp`` devices and the permission framework
    working. Tenancy lives here instead.

    A user may belong to more than one tenant - a consultant covering several
    hospitals - which is why this is a join model and not a column on the user.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships",
        db_index=True,
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships", db_index=True)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships", db_index=True)
    #: Optional narrowing of the membership to one facility.
    facility_id = models.UUIDField(null=True, blank=True, db_index=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "identity.user_membership"
        unique_together = [["user", "tenant"]]
        indexes = [models.Index(fields=["tenant", "active"])]


class BreakGlassAccess(models.Model):
    """Recorded break-glass use, requiring a reason (TEN-007).

    An append-only record. The audit trail is what makes an emergency read
    reviewable after the fact, so the reason is mandatory rather than optional
    metadata.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    user_id = models.UUIDField(db_index=True)
    resource_type = models.CharField(max_length=64)
    resource_id = models.CharField(max_length=64)
    #: Never blank: the view rejects an empty reason.
    reason = models.TextField()
    granted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "identity.break_glass_access"
        indexes = [models.Index(fields=["tenant_id", "granted_at"])]


#: The setup wizard's steps, in UI_UX design doc section 7 order. The wizard
#: is a fixed sequence — the UI stepper renders this order and nothing else —
#: so the list lives beside the model that stores progress rather than in the
#: view, and the view orchestrates its responses from it. The brief's wording
#: is authoritative: each key mirrors one step of the onboarding flow
#: (SET-001).
SETUP_STEPS = (
    "hospital_identity",
    "ownership_level",
    "address",
    "abdm_hfr_ids",
    "accreditation",
    "departments_wards_beds",
    "service_units",
    "staff_positions",
    "reference_data",
    "indicators_baseline",
)


class SetupProgress(models.Model):
    """Resumable setup wizard step state (SET-001, SET-008, SET-009).

    One row per step per tenant: the ``(tenant_id, step_key)`` pair is unique,
    so resuming a session (SET-008) or editing configuration after setup
    (SET-009) mutates the same row instead of stacking duplicates. ``payload``
    is deliberately free-form JSON — each step's form has its own shape, and
    a volatile clinical form should not be frozen into columns (AGENTS.md
    models rule). Completion is an explicit status, never implied by a
    non-empty payload: saving form data and finishing the step are different
    wizard events.

    ``updated_at`` is ``auto_now`` so the wizard can sort and display "last
    touched" state without trusting the client's clock.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETE = "complete", "Complete"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    step_key = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    payload = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "identity.setup_progress"
        # The unique index on (tenant_id, step_key) leads with tenant_id, so
        # it doubles as the tenant-scoped lookup index for the viewset's
        # ``filter(tenant_id=..., step_key=...)`` — mirroring Role's
        # declaration of both the constraint and the index.
        unique_together = [["tenant_id", "step_key"]]
        indexes = [models.Index(fields=["tenant_id", "step_key"])]


class ReferenceData(models.Model):
    """Indicator-denominator reference data (SET-006).

    Reference data is what indicator denominators divide by: catchment
    population, ambulance availability and the essential-commodity list the
    hospital commits to keeping. ``kind`` declares which of the three a row
    is so the indicator engine never has to guess from the payload's shape;
    ``key`` is the row's name within that kind (a place, a vehicle, a
    commodity); ``value`` is the parameterised payload itself, deliberately
    free-form JSON because each kind's shape differs and depends on what the
    indicator engine needs (AGENTS.md models rule).

    ``active`` exists so deactivation is a soft flip, never a delete
    (SET-011): an indicator period locked against this data stays resolvable,
    and the audit history keeps pointing at the same row.
    """

    class Kind(models.TextChoices):
        CATCHMENT_POPULATION = "catchment_population", "Catchment population"
        AMBULANCE = "ambulance", "Ambulance"
        ESSENTIAL_COMMODITY = "essential_commodity", "Essential commodity"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    kind = models.CharField(max_length=32, choices=Kind.choices)
    key = models.CharField(max_length=128)
    value = models.JSONField()
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "identity.reference_data"
        # The unique constraint is per tenant — two hospitals may both define
        # "deoni" as their catchment — so it leads with tenant_id.
        unique_together = [["tenant_id", "kind", "key"]]
        # The unique index above already covers the leftmost prefixes used by
        # the list filter (tenant_id, kind) and the duplicate probe
        # (tenant_id, kind, key); the declared index mirrors Role's and
        # SetupProgress's explicit declaration of both the constraint and the
        # index, and keeps the intent visible without relying on PG behaviour.
        indexes = [models.Index(fields=["tenant_id", "kind", "key"])]


class BaselineInput(models.Model):
    """Baseline/manual indicator inputs collected by the wizard (SET-007).

    One row per indicator-source code per period: the value the wizard files
    for a locked reporting window, keyed by the source code the indicator
    catalogue assigns. ``period`` is deliberately a short string (a month like
    ``2026-10`` or a year) rather than a date range — the indicator engine
    defines the period shape, and the wizard echoes it back verbatim.
    ``source`` records provenance: ``manual`` is the wizard entry path,
    ``imported`` an external bulk load.
    """

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        IMPORTED = "imported", "Imported"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    indicator_source_code = models.CharField(max_length=64)
    period = models.CharField(max_length=16)
    value = models.FloatField()
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)

    class Meta:
        db_table = "identity.baseline_input"
        # The list filter leads with tenant_id; the (indicator_source_code,
        # period) suffix is what a later indicator screen filters on (SET-007).
        indexes = [models.Index(fields=["tenant_id", "indicator_source_code", "period"])]


class ConfigRevision(models.Model):
    """Effective-dated snapshot of one configuration row (SET-010).

    Written by :func:`apps.identity_tenancy.services.record_revision` on every
    update of a department, ward, bed, service unit or staff position: the
    snapshot is the row's *pre-update* state, opened ``effective_from = today``
    and closed again (``effective_to`` set to yesterday) by the following
    update. A locked indicator period can therefore re-read what the
    configuration looked like at the time the period was filed, even after the
    row changed (SET-010).

    ``entity`` is the model's ``db_table`` (e.g. ``identity.department``) —
    the same convention the audit mixin uses for ``AuditEvent.entity_type`` —
    so revision history and the audit trail name a row identically, and an
    ``entity_id`` inside one entity can never collide with the same id held by
    another table. ``created_by`` mirrors the audit table's ``user_id``: a raw
    ``auth.User`` primary key, converted by the UUID field the same way the
    mixin writes it, so the two trails attribute the same change to the same
    account.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    entity = models.CharField(max_length=32)
    entity_id = models.UUIDField()
    snapshot = models.JSONField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    created_by = models.UUIDField(null=True)

    class Meta:
        db_table = "identity.config_revision"
        # The history lookup filters (tenant_id, entity, entity_id) and the
        # per-tenant list filter both lead with tenant_id, per the composite
        # index rule.
        indexes = [models.Index(fields=["tenant_id", "entity", "entity_id"])]
