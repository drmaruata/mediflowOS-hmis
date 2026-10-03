"""RIS views."""
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied

from common.tenant import TenantScopedQuerysetMixin
from .models import ImagingOrder
from .serializers import ImagingOrderSerializer


class ImagingOrderViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = ImagingOrderSerializer
    queryset = ImagingOrder.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
