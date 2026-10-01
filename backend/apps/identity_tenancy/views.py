"""Identity, tenancy and administration views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Tenant, Facility, Department, Ward, Bed, ServiceUnit, StaffPosition
from .serializers import TenantSerializer, FacilitySerializer, DepartmentSerializer, WardSerializer, BedSerializer, ServiceUnitSerializer, StaffPositionSerializer


class TenantViewSet(viewsets.ModelViewSet):
    serializer_class = TenantSerializer
    queryset = Tenant.objects.all()

    @action(detail=False, methods=["post"])
    def onboard(self, request):
        """Repeatable tenant onboarding with seed configuration."""
        serializer = TenantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class FacilityViewSet(viewsets.ModelViewSet):
    serializer_class = FacilitySerializer
    queryset = Facility.objects.all()


class DepartmentViewSet(viewsets.ModelViewSet):
    serializer_class = DepartmentSerializer
    queryset = Department.objects.all()


class WardViewSet(viewsets.ModelViewSet):
    serializer_class = WardSerializer
    queryset = Ward.objects.all()


class BedViewSet(viewsets.ModelViewSet):
    serializer_class = BedSerializer
    queryset = Bed.objects.all()


class ServiceUnitViewSet(viewsets.ModelViewSet):
    serializer_class = ServiceUnitSerializer
    queryset = ServiceUnit.objects.all()


class StaffPositionViewSet(viewsets.ModelViewSet):
    serializer_class = StaffPositionSerializer
    queryset = StaffPosition.objects.all()
