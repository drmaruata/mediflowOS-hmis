"""IPD models."""
from django.db import models
import uuid


DISPOSITION_CHOICES = [
    ("routine", "Routine"),
    ("lama", "LAMA"),
    ("absconded", "Absconded"),
    ("referred", "Referred"),
    ("death", "Death"),
    ("other", "Other"),
]


class Admission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    department_id = models.UUIDField(db_index=True)
    ward_id = models.UUIDField(db_index=True)
    bed_id = models.UUIDField(db_index=True)
    admission_time = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=64)  # OPD | referral | direct
    diagnosis = models.TextField(null=True)
    responsible_clinician_id = models.UUIDField(null=True)
    discharged_at = models.DateTimeField(null=True)
    disposition = models.CharField(max_length=32, choices=DISPOSITION_CHOICES, null=True)
    discharge_summary = models.TextField(null=True)
    transfer_from = models.UUIDField(null=True)
    transfer_to = models.UUIDField(null=True)
    transfer_reason = models.TextField(null=True)

    class Meta:
        db_table = "ipd.admission"
        indexes = [
            models.Index(fields=["tenant_id", "patient_id"]),
            models.Index(fields=["tenant_id", "bed_id"]),
        ]


class CensusSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    facility_id = models.UUIDField(db_index=True)
    ward_id = models.UUIDField(db_index=True)
    date = models.DateField(db_index=True)
    count = models.IntegerField()

    class Meta:
        db_table = "ipd.census_snapshot"
        unique_together = [["tenant_id", "ward_id", "date"]]


class BedStatus(models.Model):
    """Live bed board - refreshed via REST polling, not Channels."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bed_id = models.UUIDField(db_index=True)
    ward_id = models.UUIDField(db_index=True)
    occupied = models.BooleanField(default=False)
    patient_id = models.UUIDField(null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ipd.bed_status"
