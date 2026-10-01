"""RIS models."""
from django.db import models
import uuid


class ImagingOrder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    modality = models.CharField(max_length=32)  # CT, MRI, XR, US
    status = models.CharField(max_length=16, default="ordered")
    ordered_at = models.DateTimeField(auto_now_add=True)
    performed_at = models.DateTimeField(null=True)
    report_time = models.DateTimeField(null=True)
    dicom_study_uid = models.CharField(max_length=128, null=True)

    class Meta:
        db_table = "ris.order"
