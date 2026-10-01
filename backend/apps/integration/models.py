"""Integration adapter models."""
from django.db import models
import uuid


class IntegrationAdapter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=64)  # abdm | lab | payer | dicom | payment | notification
    adapter_type = models.CharField(max_length=32)  # rest | hl7v2 | dicom | webhook
    config = models.JSONField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "integration.adapter"
