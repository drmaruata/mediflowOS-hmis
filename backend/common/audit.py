"""Immutable audit primitives."""
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    """Append-only tamper-evident audit log."""
    tenant_id = models.UUIDField(db_index=True)
    user_id = models.UUIDField(null=True)
    action = models.CharField(max_length=16)  # create, read, update, delete, break-glass
    entity_type = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64)
    reason = models.TextField(null=True, blank=True)
    source = models.CharField(max_length=64, null=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    hash_chain = models.CharField(max_length=128, default="")

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "entity_type", "entity_id"]),
            models.Index(fields=["tenant_id", "occurred_at"]),
        ]
