"""Patient registry serializers."""
from rest_framework import serializers
from .models import Patient, IntakePoint, QRCode, ABHACallbackLog


class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = "__all__"
        read_only_fields = ["id", "created_at"]


class IntakePointSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntakePoint
        fields = "__all__"
        read_only_fields = ["id"]


class QRCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = QRCode
        fields = "__all__"
        read_only_fields = ["id"]


class ABHACallbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = ABHACallbackLog
        fields = "__all__"
        read_only_fields = ["id", "timestamp"]
