"""Pharmacy models."""
from django.db import models
import uuid


class Formulary(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    name = models.CharField(max_length=200)
    generic = models.BooleanField(default=False)
    high_alert = models.BooleanField(default=False)
    lasa = models.BooleanField(default=False)  # look-alike/sound-alike
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "pharmacy.formulary"


class StockBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    formulary_id = models.UUIDField(db_index=True)
    batch_no = models.CharField(max_length=64)
    expiry = models.DateField()
    quantity = models.IntegerField()
    stock_out_day = models.BooleanField(default=False)

    class Meta:
        db_table = "pharmacy.stock_batch"


class Dispense(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient_id = models.UUIDField(db_index=True)
    formulary_id = models.UUIDField(db_index=True)
    substituted = models.BooleanField(default=False)
    dispensed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pharmacy.dispense"
