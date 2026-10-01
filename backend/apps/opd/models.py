"""OPD models."""
from django.db import models
import uuid


class Token(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    department_id = models.UUIDField(db_index=True)
    series = models.CharField(max_length=32)
    number = models.IntegerField()
    priority = models.IntegerField(default=0)
    status = models.CharField(max_length=16, default="waiting")  # waiting | called | done | cancelled
    issued_at = models.DateTimeField(auto_now_add=True)
    called_at = models.DateTimeField(null=True)
    done_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "opd.token"
        indexes = [models.Index(fields=["tenant_id", "department_id", "status"])]


class OPDEncounter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    department_id = models.UUIDField(db_index=True)
    visit_type = models.CharField(max_length=16)  # new | follow-up
    referral_in_source = models.CharField(max_length=128, null=True)
    referral_out = models.BooleanField(default=False)
    registration_time = models.DateTimeField()
    consultation_start = models.DateTimeField(null=True)
    consultation_end = models.DateTimeField(null=True)

    class Meta:
        db_table = "opd.encounter"
        # registration_time and consultation_start are the structured fields
        # OPD wait-time indicators are computed from (architecture doc
        # section 10, "quality by design").
        indexes = [
            models.Index(fields=["tenant_id", "department_id", "registration_time"]),
        ]
