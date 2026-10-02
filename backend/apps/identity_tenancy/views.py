"""Identity and administration views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import BreakGlassAccess, Department, Facility, Role, ServiceUnit, StaffPosition, Tenant, Ward, Bed, UserMembership
from .serializers import (
    BreakGlassAccessSerializer, DepartmentSerializer, FacilitySerializer,
    RoleSerializer, ServiceUnitSerializer, StaffPositionSerializer,
    TenantSerializer, WardSerializer, BedSerializer, UserMembershipSerializer,
)


class TenantViewSet(viewsets.ModelViewSet):
    """Tenants are the tenancy root, so they are not tenant-scoped."""
    serializer_class = TenantSerializer
    queryset = Tenant.objects.all()

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


class RoleViewSet(viewsets.ModelViewSet):
    """Role management (TEN-004)."""
    serializer_class = RoleSerializer
    queryset = Role.objects.all()


class UserMembershipViewSet(viewsets.ModelViewSet):
    """Tenant membership assignment (TEN-004)."""
    serializer_class = UserMembershipSerializer
    queryset = UserMembership.objects.all()

    def perform_create(self, serializer):
        """Stamp the tenant from the request."""
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("A tenant must be resolved before creating a membership.")
        serializer.save(**{"tenant_id": tenant_id})


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
