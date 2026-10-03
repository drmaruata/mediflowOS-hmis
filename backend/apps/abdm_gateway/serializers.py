"""ABDM gateway serializers."""
from rest_framework import serializers
from .models import ABHACallbackLog


class ABHACallbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = ABHACallbackLog
        fields = "__all__"
        read_only_fields = ["id", "timestamp", "tenant_id"]


class ABHACallbackAckSerializer(serializers.Serializer):
    """Acknowledgement returned to the ABDM gateway."""
    status = serializers.CharField()
    token = serializers.CharField(required=False, allow_null=True)
    request_id = serializers.CharField()
    patient_id = serializers.UUIDField(required=False, allow_null=True)
