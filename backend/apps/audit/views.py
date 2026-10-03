"""Audit views."""
from rest_framework import viewsets

from common.tenant import TenantScopedQuerysetMixin
from .models import AuditEvent
from .serializers import AuditEventSerializer


class AuditLogViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """Audit log — read-only, tenant-scoped (AUD-003)."""
    serializer_class = AuditEventSerializer
    queryset = AuditEvent.objects.all()

    def list(self, request, *args, **kwargs):
        """List audit entries for the tenant.

        If a resource_type and resource_id are supplied, filters to that
        resource — audit drill-down for patient record access history.
        """
        queryset = self.get_queryset()
        resource_type = request.query_params.get("resource_type")
        resource_id = request.query_params.get("resource_id")
        if resource_type:
            queryset = queryset.filter(entity_type=resource_type)
            if resource_id:
                queryset = queryset.filter(entity_id=resource_id)
        return super().list(request, *args, **kwargs)
