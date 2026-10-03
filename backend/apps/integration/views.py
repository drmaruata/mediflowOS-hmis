"""Integration views."""
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied

from common.tenant import TenantScopedQuerysetMixin
from .models import IntegrationAdapter, WebhookEndpoint
from .serializers import IntegrationAdapterSerializer, WebhookEndpointSerializer


class IntegrationAdapterViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = IntegrationAdapterSerializer
    queryset = IntegrationAdapter.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})


class WebhookEndpointViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = WebhookEndpointSerializer
    queryset = WebhookEndpoint.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
