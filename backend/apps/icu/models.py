"""ICU models."""
from django.db import models
import uuid


class VitalsFlowsheet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    recorded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    type = models.CharField(max_length=32)  # hr, bp, spo2, rr, temp, map
    value = models.FloatField()
    unit = models.CharField(max_length=16)
    source = models.CharField(max_length=32)  # manual | device

    class Meta:
        db_table = "icu.vitals"
        indexes = [models.Index(fields=["tenant_id", "patient_id", "recorded_at"])]


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    admission_id = models.UUIDField(db_index=True)
    device_type = models.CharField(max_length=64)  # ventilator, catheter, etc.
    inserted_at = models.DateTimeField()
    removed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "icu.device"
        # Device days are an ICU indicator input (architecture doc section 10).
        indexes = [models.Index(fields=["tenant_id", "admission_id", "device_type"])]
