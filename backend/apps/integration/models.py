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
    # INT-002: which API version of the vendor's contract this row speaks — the
    # ABDM adapter serves an older and a newer profile-share version (SRS INT-002,
    # architecture doc section 8.2). The supported values are ``v2`` and ``v3``,
    # enforced by the registry in ``apps.abdm_gateway.client`` rather than by
    # ``choices=`` here: the vocabulary is a service-layer rule (a business rule
    # belongs in the service, not the model), and the gateway's own version
    # labels are still to be confirmed against the sandbox spec (REG-009), so a
    # model-level enumeration would freeze a guess into the schema.
    #
    # The default is ``v2``, which is exactly the single unversioned shape the
    # callback returned before version support existed: that is what makes this
    # field's migration behaviour-preserving for every row that already exists,
    # and what lets an adapter be created without naming a version.
    api_version = models.CharField(max_length=16, default="v2")
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
