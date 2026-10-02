"""Platform models (PLT-001 to PLT-008)."""
from django.db import models
import uuid


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    user_id = models.UUIDField(db_index=True)
    title = models.CharField(max_length=400)
    body = models.TextField()
    type = models.CharField(max_length=32)  # alert | info | critical
    persisted = models.BooleanField(default=False)
    delivered = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform.notification"
        indexes = [models.Index(fields=["tenant_id", "user_id", "read_at"])]


class PlatformFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    filename = models.CharField(max_length=500)
    file_url = models.URLField()
    file_type = models.CharField(max_length=64)
    uploaded_by = models.UUIDField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform.file"
        indexes = [models.Index(fields=["tenant_id", "uploaded_at"])]


class ScheduledJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    job_type = models.CharField(max_length=64)  # indicator_computation | report_generation | sync
    status = models.CharField(max_length=16, default="pending")  # pending | running | completed | failed
    scheduled_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "platform.scheduled_job"
        indexes = [models.Index(fields=["tenant_id", "status", "scheduled_at"])]
