"""Emergency models."""
from django.db import models
import uuid


class Triage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    category = models.CharField(max_length=16)  # I | II | III | IV | V
    arrival_time = models.DateTimeField(auto_now_add=True)
    first_assessment_time = models.DateTimeField(null=True)
    mlc_flag = models.BooleanField(default=False)  # medico-legal case

    class Meta:
        db_table = "emergency.triage"
