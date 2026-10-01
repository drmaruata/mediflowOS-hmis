"""OT/surgery models."""
from django.db import models
import uuid


class OperationSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    theatre = models.CharField(max_length=64)
    patient_id = models.UUIDField(db_index=True)
    surgeon_id = models.UUIDField(null=True)
    anaesthetist_id = models.UUIDField(null=True)
    scheduled_start = models.DateTimeField(db_index=True)
    scheduled_end = models.DateTimeField(null=True)
    conflict_detected = models.BooleanField(default=False)

    class Meta:
        db_table = "ot.schedule"


class SurgeryRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    schedule_id = models.UUIDField(db_index=True)
    pre_op_checklist = models.JSONField(null=True)
    anaesthesia_record = models.JSONField(null=True)
    operative_note = models.TextField(null=True)
    prophylaxis_time = models.DateTimeField(null=True)
    incision_time = models.DateTimeField(null=True)
    unplanned_return = models.BooleanField(default=False)

    class Meta:
        db_table = "ot.record"
        indexes = [
            models.Index(fields=["tenant_id", "schedule_id", "incision_time"]),
        ]
