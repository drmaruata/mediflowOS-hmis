"""Patient registry serializers."""
from rest_framework import serializers
from .models import Patient, IntakePoint, QRCode


class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = "__all__"
        read_only_fields = ["id", "created_at", "tenant_id"]


class IntakePointSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntakePoint
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class QRCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = QRCode
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
