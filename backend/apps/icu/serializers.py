"""ICU serializers."""
from rest_framework import serializers
from .models import Device, VitalsFlowsheet


class VitalsFlowsheetSerializer(serializers.ModelSerializer):
    class Meta:
        model = VitalsFlowsheet
        fields = "__all__"
        read_only_fields = ["id", "recorded_at", "tenant_id"]


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
