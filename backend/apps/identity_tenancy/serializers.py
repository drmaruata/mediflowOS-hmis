"""Serializers for identity and tenancy."""
from rest_framework import serializers
from .models import (
    BreakGlassAccess, Department, Facility, Role, ServiceUnit, StaffPosition,
    Tenant, Ward, Bed, UserMembership,
)


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
        read_only_fields = ["id", "tenant_id"]


class BedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bed
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class ServiceUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceUnit
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class StaffPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffPosition
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = "__all__"
        read_only_fields = ["id", "created_at"]


class UserMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserMembership
        fields = "__all__"
        read_only_fields = ["id", "active"]


class BreakGlassAccessSerializer(serializers.ModelSerializer):
    class Meta:
        model = BreakGlassAccess
        fields = "__all__"
        read_only_fields = ["id", "granted_at", "tenant_id"]
