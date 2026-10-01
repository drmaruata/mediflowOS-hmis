"""Blood Bank models (BBK-001 to BBK-008)."""
from django.db import models
import uuid


class Donor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    name = models.CharField(max_length=200)
    blood_group = models.CharField(max_length=8)
    registration_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bbk.donor"


class Donation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    donor_id = models.UUIDField(db_index=True)
    collection_time = models.DateTimeField(auto_now_add=True)
    testing_status = models.CharField(max_length=32, default="pending")  # pending | passed | failed
    mandatory_tests = models.JSONField(default=dict)

    class Meta:
        db_table = "bbk.donation"


class BloodComponent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    donation_id = models.UUIDField(db_index=True)
    component_type = models.CharField(max_length=32)  # RBC, FFP, Platelet, Cryo
    blood_group = models.CharField(max_length=8)
    status = models.CharField(max_length=32, default="available")  # available | issued | discarded | expired
    collection_date = models.DateField()
    expiry_date = models.DateField()

    class Meta:
        db_table = "bbk.component"


class Requisition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(null=True, db_index=True)
    component_id = models.UUIDField(db_index=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    issued_at = models.DateTimeField(null=True)
    source = models.CharField(max_length=32, null=True)  # voluntary | replacement

    class Meta:
        db_table = "bbk.requisition"


class CrossMatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requisition_id = models.UUIDField(db_index=True)
    result = models.CharField(max_length=32)  # compatible | incompatible | pending
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bbk.crossmatch"


class TransfusionReaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requisition_id = models.UUIDField(db_index=True)
    component_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    reaction_type = models.CharField(max_length=64)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bbk.reaction"
