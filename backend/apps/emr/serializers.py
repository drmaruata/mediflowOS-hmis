"""EMR serializers."""
from rest_framework import serializers
from .models import ClinicalDocument, ProblemList, SafetyEvent


class ClinicalDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicalDocument
        fields = "__all__"
        read_only_fields = ["id", "created_at", "tenant_id"]


class ProblemListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProblemList
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class SafetyEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafetyEvent
        fields = "__all__"
        read_only_fields = ["id", "recorded_at", "tenant_id"]
