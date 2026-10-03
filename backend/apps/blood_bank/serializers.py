"""Blood Bank serializers."""
from rest_framework import serializers
from .models import (
    BloodComponent, CrossMatch, Donation, Donor,
    Requisition, TransfusionReaction,
)


class DonorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Donor
        fields = "__all__"
        read_only_fields = ["id", "registration_time", "tenant_id"]


class DonationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Donation
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class BloodComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BloodComponent
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class RequisitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Requisition
        fields = "__all__"
        read_only_fields = ["id", "requested_at", "tenant_id"]


class CrossMatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrossMatch
        fields = "__all__"
        read_only_fields = ["id", "recorded_at", "tenant_id"]


class TransfusionReactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransfusionReaction
        fields = "__all__"
        read_only_fields = ["id", "recorded_at", "tenant_id"]
