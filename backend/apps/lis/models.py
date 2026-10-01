"""LIS models."""
from django.db import models
import uuid


class LabOrder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    test_code = models.CharField(max_length=64)
    status = models.CharField(max_length=16, default="ordered")  # ordered | collected | received | reported
    order_time = models.DateTimeField(auto_now_add=True)
    collection_time = models.DateTimeField(null=True)
    receipt_time = models.DateTimeField(null=True)
    report_time = models.DateTimeField(null=True)

    class Meta:
        db_table = "lis.order"


class LabResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    order_id = models.UUIDField(db_index=True)
    result = models.JSONField()
    critical = models.BooleanField(default=False)
    acknowledged = models.BooleanField(default=False)
    ack_time = models.DateTimeField(null=True)
    released = models.BooleanField(default=False)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "lis.result"
        # Critical-result acknowledgement is an indicator input, and version
        # supports append-only amendment rather than destructive correction.
        indexes = [
            models.Index(fields=["tenant_id", "order_id", "critical"]),
            models.Index(fields=["tenant_id", "order_id", "version"]),
        ]
