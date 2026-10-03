"""LIS views."""
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import LabOrder, LabResult
from .serializers import LabOrderSerializer, LabResultSerializer


class LabOrderViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = LabOrderSerializer
    queryset = LabOrder.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=True, methods=["post"])
    def collect(self, request, pk=None):
        """Record sample collection."""
        order = self.get_object()
        order.status = "collected"
        order.collection_time = timezone.now()
        order.save(update_fields=["status", "collection_time"])
        return Response(LabOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        """Release result after validation."""
        order = self.get_object()
        order.status = "reported"
        order.report_time = timezone.now()
        order.save(update_fields=["status", "report_time"])
        return Response(LabOrderSerializer(order).data)


class LabResultViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = LabResultSerializer
    queryset = LabResult.objects.all()

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        """Acknowledge a critical result."""
        result = self.get_object()
        result.acknowledged = True
        result.ack_time = timezone.now()
        result.save(update_fields=["acknowledged", "ack_time"])
        return Response(LabResultSerializer(result).data)
