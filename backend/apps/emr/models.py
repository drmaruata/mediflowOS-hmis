"""EMR models."""
from django.db import models
import uuid


class ClinicalDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    doc_type = models.CharField(max_length=64)  # consultation | discharge_summary | note
    content = models.JSONField()
    version = models.IntegerField(default=1)
    amended_from = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.UUIDField()

    class Meta:
        db_table = "emr.document"


class ProblemList(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    onset_date = models.DateField(null=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        db_table = "emr.problem"
        indexes = [models.Index(fields=["tenant_id", "patient_id", "resolved"])]


class SafetyEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    event_type = models.CharField(max_length=64)  # fall | pressure_injury | infection
    severity = models.CharField(max_length=16)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "emr.safety_event"
