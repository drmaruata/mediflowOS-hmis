"""Patient registry models (REG-001 to REG-013, ABD-001 to ABD-017)."""
from django.db import models
import uuid


class Patient(models.Model):
    """Single patient record per tenant (UHID-based)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    uhid = models.CharField(max_length=32, db_index=True)
    abha_address = models.CharField(max_length=128, null=True, blank=True)
    abha_number = models.CharField(max_length=14, null=True, blank=True, db_index=True)
    verification_status = models.CharField(max_length=16, default="pending")  # pending | verified
    verified_at = models.DateTimeField(null=True, blank=True)
    demographics = models.JSONField()
    contact = models.JSONField(null=True)
    address = models.JSONField(null=True)
    scheme_category = models.JSONField(null=True)
    consent_flags = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "registry.patient"
        indexes = [
            models.Index(fields=["tenant_id", "abha_number"]),
            models.Index(fields=["tenant_id", "uhid"]),
        ]
        # UHID is unique *within a tenant*, not globally: the class docstring
        # promises one record per tenant. A bare unique=True would stop two
        # hospitals from both issuing UH0001.
        unique_together = [["tenant_id", "uhid"]]


class IntakePoint(models.Model):
    """Generic intake point model for Scan and Share extensibility."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    facility = models.ForeignKey("identity_tenancy.Facility", on_delete=models.CASCADE, related_name="intake_points", db_index=True)
    type = models.CharField(max_length=32)  # opd|pharmacy|lab|billing
    counter_id = models.CharField(max_length=32, null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "registry.intake_point"
        indexes = [models.Index(fields=["tenant_id", "facility", "type"])]


class QRCode(models.Model):
    """Facility/counter/department QR codes for ABDM Scan and Share."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    facility = models.ForeignKey("identity_tenancy.Facility", on_delete=models.CASCADE, related_name="qr_codes", db_index=True)
    intake_point = models.ForeignKey(IntakePoint, on_delete=models.SET_NULL, null=True, blank=True, related_name="qr_codes")
    encode_data = models.TextField()  # ABDM HIP ID + intake code
    active = models.BooleanField(default=True)
    regenerated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "registry.qr_code"
        indexes = [models.Index(fields=["tenant_id", "facility", "active"])]


class ABHACallbackLog(models.Model):
    """Idempotent log of ABDM profile-share callbacks."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    request_id = models.CharField(max_length=128, unique=True, db_index=True)
    facility_abdm_id = models.CharField(max_length=64, db_index=True)
    ip = models.GenericIPAddressField(null=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    profile = models.JSONField(null=True)
    matched_patient_id = models.UUIDField(null=True, blank=True)
    token_issued = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=32)  # ok | rejected | duplicate

    class Meta:
        db_table = "registry.abdm_callback_log"
        indexes = [models.Index(fields=["tenant_id", "request_id"])]


class PatientSequence(models.Model):
    """Per-tenant, per-month counter that backs server-issued UHIDs (REG-001).

    One row exists per ``(tenant, kind, period)``; ``next_value`` is the next
    number to issue, so the first call creates the row at 1 and leaves it at
    2. ``period`` is the ``%Y-%m`` month of registration, which is what makes
    a UHID restart at ``000001`` each month and stay unique within the tenant.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    kind = models.CharField(max_length=16, default="uhid")
    period = models.CharField(max_length=16)
    next_value = models.BigIntegerField(default=1)

    class Meta:
        db_table = "registry.sequence"
        unique_together = [["tenant_id", "kind", "period"]]
