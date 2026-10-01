"""Platform services models (PLT-001 to PLT-008)."""
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform.notification"


class FeatureFlag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    flag = models.CharField(max_length=64, db_index=True)
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "platform.feature_flag"
        unique_together = [["tenant_id", "flag"]]
