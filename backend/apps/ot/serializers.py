"""OT serializers."""
from rest_framework import serializers
from .models import OperationSchedule, SurgeryRecord


class OperationScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperationSchedule
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class SurgeryRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurgeryRecord
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
