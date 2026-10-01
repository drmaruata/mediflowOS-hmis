"""Billing and insurance models."""
from django.db import models
import uuid


class Tariff(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    service = models.CharField(max_length=120)
    ward_class = models.CharField(max_length=32, null=True)
    payer_category = models.CharField(max_length=64, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "billing.tariff"


class Invoice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    type = models.CharField(max_length=16)  # opd | ipd
    total = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=16, default="draft")  # draft | paid | refunded
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing.invoice"


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    invoice_id = models.UUIDField(db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=32)
    receipt_no = models.CharField(max_length=64, null=True)
    paid_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing.payment"
        indexes = [models.Index(fields=["tenant_id", "invoice_id", "paid_at"])]


class Claim(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    invoice_id = models.UUIDField(db_index=True)
    payer = models.CharField(max_length=64)
    pre_auth_no = models.CharField(max_length=64, null=True)
    status = models.CharField(max_length=32, default="pending")  # pending | approved | rejected | paid

    class Meta:
        db_table = "billing.claim"
        indexes = [models.Index(fields=["tenant_id", "status", "invoice_id"])]
