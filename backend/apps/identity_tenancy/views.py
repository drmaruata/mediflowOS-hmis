"""Identity, tenancy and administration views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import Tenant, Facility, Department, Ward, Bed, ServiceUnit, StaffPosition
from .serializers import (
    TenantSerializer,
    FacilitySerializer,
    DepartmentSerializer,
    WardSerializer,
    BedSerializer,
    ServiceUnitSerializer,
    StaffPositionSerializer,
)


class TenantViewSet(viewsets.ModelViewSet):
    """Tenants are the tenancy root, so they are not tenant-scoped.

    Access control for onboarding is a platform-administrator concern (TEN-010)
    and is handled by permissions on this viewset rather than by tenant
    scoping. It is not reachable anonymously: the project default is
    ``IsAuthenticated`` (see REST_FRAMEWORK in config/settings/base.py).
    """

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
    """Facility and Department carry ``tenant`` (a FK) rather than a plain column.

    Django stores that FK in a column named ``tenant_id``, so the RLS policy
    reads the same ``tenant_id`` column as every other table and filtering
    ``tenant_id=...`` resolves against that column without a join.
    """

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