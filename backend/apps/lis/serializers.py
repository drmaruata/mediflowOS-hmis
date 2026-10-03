"""LIS serializers."""
from rest_framework import serializers
from .models import LabOrder, LabResult


class LabOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabOrder
        fields = "__all__"
        read_only_fields = ["id", "order_time", "tenant_id"]


class LabResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabResult
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
