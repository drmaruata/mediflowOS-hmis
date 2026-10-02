"""Integration models."""
from django.db import models
import uuid


class IntegrationAdapter(models.Model):
    """Per-tenant integration adapter configuration.

    Scoped to a tenant because ``config`` holds the facility's own credentials
    and endpoints (ABDM HIP secret, lab analyser address, payer credentials).
    A shared adapter row would leak one hospital's credentials to another.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    name = models.CharField(max_length=64)  # abdm | lab | payer | dicom | payment | notification
    adapter_type = models.CharField(max_length=32)  # rest | hl7v2 | dicom | webhook
    config = models.JSONField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "integration.adapter"
        unique_together = [["tenant_id", "name"]]
        indexes = [models.Index(fields=["tenant_id", "name", "active"])]


class WebhookEndpoint(models.Model):
    """Configured webhook destinations per tenant."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    url = models.URLField()
    events = models.JSONField(default=list)  # list of event type strings
    secret = models.CharField(max_length=255, null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "integration.webhook"
        indexes = [models.Index(fields=["tenant_id", "active"])]
