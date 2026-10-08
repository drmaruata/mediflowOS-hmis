"""Identity and administration views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import BreakGlassAccess, Department, Facility, Role, ServiceUnit, StaffPosition, Tenant, Ward, Bed, UserMembership
from .permissions import RequirePermission, WritePermissionMixin
from .serializers import (
    BreakGlassAccessSerializer, DepartmentSerializer, FacilitySerializer,
    RoleSerializer, ServiceUnitSerializer, StaffPositionSerializer,
    TenantSerializer, WardSerializer, BedSerializer, UserMembershipSerializer,
)


class TenantViewSet(viewsets.ModelViewSet):
    """Tenants are the tenancy root, so they are not tenant-scoped.

    They are platform-owned instead: every method — list, detail, create and
    the onboard action — requires the ``platform.tenants.manage`` claim
    (TEN-004, TEN-010), which the platform-scope role (``Role.tenant is None``)
    is expected to hold. A tenant administrator must be able to neither
    enumerate other hospitals' tenants nor mint new ones.
    """
    serializer_class = TenantSerializer
    queryset = Tenant.objects.all()

    def get_permissions(self):
        # Appended after the defaults, so anonymous requests still fail as 401
        # (IsAuthenticated first) and the MFA gate stays in force — see
        # common/mfa.py on views replacing DEFAULT_PERMISSION_CLASSES.
        return [*super().get_permissions(), RequirePermission("platform.tenants.manage")]

    @action(detail=False, methods=["post"])
    def onboard(self, request):
        """Repeatable tenant onboarding with seed configuration (TEN-010)."""
        serializer = TenantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class FacilityViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = FacilitySerializer
    queryset = Facility.objects.all()


class DepartmentViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = DepartmentSerializer
    queryset = Department.objects.all()


class WardViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = WardSerializer
    queryset = Ward.objects.all()


class BedViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = BedSerializer
    queryset = Bed.objects.all()


class ServiceUnitViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = ServiceUnitSerializer
    queryset = ServiceUnit.objects.all()


class StaffPositionViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = StaffPositionSerializer
    queryset = StaffPosition.objects.all()


class RoleViewSet(WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Role management (TEN-004).

    Scoping keeps each hospital's role catalogue — names and permission
    bundles — out of every other tenant's list. Platform-scope roles
    (``tenant is None``) belong to no tenant's list either: exposing them
    here would let a tenant administrator edit the platform's own roles.
    Writes require the ``identity.roles.write`` claim.
    """
    serializer_class = RoleSerializer
    queryset = Role.objects.all()
    write_permission = "identity.roles.write"


class UserMembershipViewSet(WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Tenant membership assignment (TEN-004).

    Tenant stamping and the audit trail (AUD-001) both come from
    ``TenantScopedQuerysetMixin``'s ``perform_*`` hooks — the local
    ``perform_create`` this viewset used to carry duplicated the stamping and
    wrote no audit row. Writes require the ``identity.memberships.write`` claim.
    """
    serializer_class = UserMembershipSerializer
    queryset = UserMembership.objects.all()
    write_permission = "identity.memberships.write"


class BreakGlassViewSet(viewsets.ViewSet):
    """Recorded break-glass access (TEN-007)."""
    permission_classes = [IsAuthenticated]

    def list(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        queryset = BreakGlassAccess.objects.filter(tenant_id=tenant_id)
        return Response(BreakGlassAccessSerializer(queryset, many=True).data)

    def create(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("A tenant must be resolved before break-glass access.")
        serializer = BreakGlassAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id, user_id=request.user.pk)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
