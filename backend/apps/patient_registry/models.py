"""Patient registry models (REG-001 to REG-013, ABD-001 to ABD-017)."""
from django.db import models
import uuid


class Patient(models.Model):
    """Single patient record per tenant (UHID-based)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    uhid = models.CharField(max_length=32, unique=True, db_index=True)
    abha_address = models.CharField(max_length=128, null=True, blank=True)
    abha_number = models.CharField(max_length=14, null=True, blank=True, db_index=True)
    verification_status = models.CharField(max_length=16, default="provisional")  # provisional | verified
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


class IntakePoint(models.Model):
    """Generic intake point model for Scan and Share extensibility."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.ForeignKey("identity_tenancy.Facility", on_delete=models.CASCADE, related_name="intake_points", db_index=True)
    type = models.CharField(max_length=32)  # opd|pharmacy|lab|billing
    counter_id = models.CharField(max_length=32, null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "registry.intake_point"


class QRCode(models.Model):
    """Facility/counter/department QR codes for ABDM Scan and Share."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.ForeignKey("identity_tenancy.Facility", on_delete=models.CASCADE, related_name="qr_codes", db_index=True)
    intake_point = models.ForeignKey(IntakePoint, on_delete=models.SET_NULL, null=True, blank=True, related_name="qr_codes")
    encode_data = models.TextField()  # ABDM HIP ID + intake code
    active = models.BooleanField(default=True)
    regenerated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "registry.qr_code"


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
