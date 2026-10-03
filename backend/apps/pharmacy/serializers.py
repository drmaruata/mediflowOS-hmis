"""Pharmacy serializers."""
from rest_framework import serializers
from .models import Dispense, Formulary, StockBatch


class FormularySerializer(serializers.ModelSerializer):
    class Meta:
        model = Formulary
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class StockBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockBatch
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class DispenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dispense
        fields = "__all__"
        read_only_fields = ["id", "dispensed_at", "tenant_id"]
