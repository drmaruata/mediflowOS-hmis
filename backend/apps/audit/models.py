"""Audit models (AUD-001 to AUD-004)."""
from django.db import models
import uuid


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    user_id = models.UUIDField(null=True)
    action = models.CharField(max_length=16)  # create, read, update, delete, break-glass
    entity_type = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64)
    reason = models.TextField(null=True)
    #: Provenance marker for programmatic writes (e.g. ``"qr.regenerate"``).
    #: Distinct from ``reason``, which is the human break-glass justification;
    #: a machine-initiated change carries no break-glass header and still has
    #: to be findable as its own kind of event.
    source = models.CharField(max_length=64, null=True, blank=True)
    source_ip = models.GenericIPAddressField(null=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    hash_chain = models.CharField(max_length=128, default="")

    class Meta:
        db_table = "audit.event"
        indexes = [
            models.Index(fields=["tenant_id", "entity_type", "entity_id"]),
            models.Index(fields=["tenant_id", "occurred_at"]),
        ]
