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
        # tenant is server-owned: TenantScopedQuerysetMixin stamps it on
        # create, and a writable tenant on update would let a caller move a
        # role into another tenant (common/tenant.py states this contract).
        read_only_fields = ["id", "created_at", "tenant"]

    def validate_permissions(self, value):
        """Refuse platform-scope codes on tenant-scoped roles (TEN-004).

        Platform scope is defined as ``Role.tenant is None``, but until now
        nothing enforced it: a tenant admin holding ``identity.roles.write``
        could PATCH ``platform.tenants.manage`` onto their own role, re-login,
        and pass the ``TenantViewSet`` gate that enumerates and mints
        hospitals. This is the write-path half of that constraint —
        token-level scope binding (checking the role's scope at claim
        issuance) is deliberately deferred.

        Updates consult the stored role's tenant. Creates are refused
        outright rather than consulted: ``RoleViewSet`` is tenant-scoped and
        stamps the request's tenant in ``perform_create``, so a role created
        through the API is always tenant-owned — a platform-scoped create
        would need a platform-level viewset, which does not exist.

        Only codes literally starting with ``platform.`` are rejected, which
        is exactly the set ``RequirePermission`` can ever match (exact list
        membership), so a padded or non-string entry grants nothing.

        List elements and dict keys are both checked because ``tokens.py``
        builds the claim with ``list(role.permissions or [])`` — ``list()`` on
        a dict yields its *keys*, so a dict key carrying a platform code would
        grant it just as a list element would. Any other JSON shape passes
        through untouched: a non-list claim can never satisfy
        ``RequirePermission``, so nothing in it can grant.
        """
        if isinstance(value, list):
            candidates = value
        elif isinstance(value, dict):
            candidates = list(value.keys())
        else:
            # See the docstring: a string iterates to single characters when
            # the claim is built, so no non-list shape can ever satisfy
            # RequirePermission — pass it through instead of raising here.
            return value
        platform_codes = [
            code
            for code in candidates
            if isinstance(code, str) and code.startswith("platform.")
        ]
        if not platform_codes:
            return value
        # A create (self.instance is None) is always tenant-owned — see above.
        if self.instance is None or self.instance.tenant is not None:
            raise serializers.ValidationError(
                f"Platform-scope permissions {platform_codes} are reserved for "
                "platform-scoped roles (Role.tenant is None)."
            )
        return value


class UserMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserMembership
        fields = "__all__"
        read_only_fields = ["id", "active", "tenant"]


class BreakGlassAccessSerializer(serializers.ModelSerializer):
    class Meta:
        model = BreakGlassAccess
        fields = "__all__"
        read_only_fields = ["id", "granted_at", "tenant_id"]
