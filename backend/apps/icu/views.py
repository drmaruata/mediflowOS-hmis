"""ICU views."""
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied

from common.tenant import TenantScopedQuerysetMixin
from .models import Device, VitalsFlowsheet
from .serializers import DeviceSerializer, VitalsFlowsheetSerializer


class VitalsFlowsheetViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = VitalsFlowsheetSerializer
    queryset = VitalsFlowsheet.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})


class DeviceViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = DeviceSerializer
    queryset = Device.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
