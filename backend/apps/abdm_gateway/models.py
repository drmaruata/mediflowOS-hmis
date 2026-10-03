"""ABDM gateway models."""
from django.db import models
import uuid


class ABHACallbackLog(models.Model):
    """Idempotent log of ABDM profile-share callbacks."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    request_id = models.CharField(max_length=128, unique=True, db_index=True)
    facility_abdm_id = models.CharField(max_length=64, db_index=True)
    ip = models.GenericIPAddressField(null=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    profile = models.JSONField(null=True)
    matched_patient_id = models.UUIDField(null=True, blank=True)
    token_issued = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=32)  # ok | rejected | duplicate

    class Meta:
        db_table = "abdm.callback_log"
        indexes = [models.Index(fields=["tenant_id", "request_id"])]
