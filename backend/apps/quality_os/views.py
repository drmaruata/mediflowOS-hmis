"""Quality OS views."""
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import CAPA, IndicatorDef, IndicatorSourceDocument, IndicatorValue, QualityFact, Framework, FrameworkEdition
from .serializers import (
    CAPASerializer, FrameworkSerializer, FrameworkEditionSerializer,
    IndicatorDefSerializer, IndicatorSourceDocumentSerializer,
    IndicatorValueSerializer, QualityFactSerializer,
)


class FrameworkViewSet(viewsets.ModelViewSet):
    """Framework definitions — global, not tenant-scoped."""
    serializer_class = FrameworkSerializer
    queryset = Framework.objects.all()


class FrameworkEditionViewSet(viewsets.ModelViewSet):
    serializer_class = FrameworkEditionSerializer
    queryset = FrameworkEdition.objects.all()


class IndicatorSourceDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = IndicatorSourceDocumentSerializer
    queryset = IndicatorSourceDocument.objects.all()


class IndicatorDefViewSet(viewsets.ModelViewSet):
    """Indicator definitions — global source catalogue."""
    serializer_class = IndicatorDefSerializer
    queryset = IndicatorDef.objects.all()


class IndicatorValueViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Tenant-scoped indicator values."""
    serializer_class = IndicatorValueSerializer
    queryset = IndicatorValue.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=False, methods=["get"])
    def dashboard(self, request):
        """Dashboard view for enabled indicators."""
        indicator_id = request.query_params.get("indicator_id")
        period_start = request.query_params.get("period_start")
        queryset = self.get_queryset()
        if indicator_id:
            queryset = queryset.filter(indicator_id=indicator_id)
        if period_start:
            queryset = queryset.filter(period_start__gte=period_start)
        return Response(IndicatorValueSerializer(queryset.order_by("-period_start"), many=True).data)


class CAPAViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """CAPA workflow."""
    serializer_class = CAPASerializer
    queryset = CAPA.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Close a CAPA with effectiveness evidence."""
        capa = self.get_object()
        capa.status = "closed"
        capa.closed_at = timezone.now()
        capa.save(update_fields=["status", "closed_at"])
        return Response(CAPASerializer(capa).data)


class QualityFactViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Append-only quality facts."""
    serializer_class = QualityFactSerializer
    queryset = QualityFact.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
