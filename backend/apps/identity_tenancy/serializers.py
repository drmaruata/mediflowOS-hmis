"""Serializers for identity and tenancy."""
from rest_framework import serializers
from .models import Tenant, Facility, Department, Ward, Bed, ServiceUnit, StaffPosition


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "tier", "accreditation_profile", "db_mode", "created_at"]
        read_only_fields = ["id", "created_at"]


class FacilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Facility
        fields = "__all__"
        read_only_fields = ["id", "created_at"]


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = "__all__"
        read_only_fields = ["id"]


class WardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ward
        fields = "__all__"
        read_only_fields = ["id"]


class BedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bed
        fields = "__all__"
        read_only_fields = ["id"]


class ServiceUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceUnit
        fields = "__all__"
        read_only_fields = ["id"]


class StaffPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffPosition
        fields = "__all__"
        read_only_fields = ["id"]
