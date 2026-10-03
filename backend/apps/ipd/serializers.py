"""IPD serializers."""
from rest_framework import serializers
from .models import Admission, BedStatus, CensusSnapshot


class AdmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Admission
        fields = "__all__"
        read_only_fields = ["id", "admission_time", "tenant_id"]


class BedStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = BedStatus
        fields = "__all__"
        read_only_fields = ["id", "updated_at", "tenant_id"]


class CensusSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = CensusSnapshot
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
