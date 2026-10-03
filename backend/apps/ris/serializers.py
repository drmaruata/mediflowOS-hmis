"""RIS serializers."""
from rest_framework import serializers
from .models import ImagingOrder


class ImagingOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImagingOrder
        fields = "__all__"
        read_only_fields = ["id", "ordered_at", "tenant_id"]
