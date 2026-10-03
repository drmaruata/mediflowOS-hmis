"""Pharmacy views."""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import Dispense, Formulary, StockBatch
from .serializers import DispenseSerializer, FormularySerializer, StockBatchSerializer


class FormularyViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = FormularySerializer
    queryset = Formulary.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})


class StockBatchViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = StockBatchSerializer
    queryset = StockBatch.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=False, methods=["get"])
    def stockouts(self, request):
        """List items currently in stock-out status."""
        queryset = self.get_queryset().filter(stock_out_day=True)
        return Response(StockBatchSerializer(queryset, many=True).data)


class DispenseViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = DispenseSerializer
    queryset = Dispense.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
