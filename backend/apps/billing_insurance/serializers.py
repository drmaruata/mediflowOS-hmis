"""Billing serializers."""
from rest_framework import serializers
from .models import Claim, Invoice, Payment, Tariff


class TariffSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tariff
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = "__all__"
        read_only_fields = ["id", "created_at", "tenant_id"]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = "__all__"
        read_only_fields = ["id", "paid_at", "tenant_id"]


class ClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = Claim
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
