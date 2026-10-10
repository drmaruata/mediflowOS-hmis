"""Audit views."""
from rest_framework import viewsets

from common.tenant import TenantScopedQuerysetMixin
from .models import AuditEvent
from .serializers import AuditEventSerializer


class AuditLogViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """Audit log — read-only, tenant-scoped (AUD-003).

    Drill-down narrows the trail to one resource for a "when was this patient
    record opened?" query: ``?entity_type=<table>`` selects one resource kind
    and ``?entity_id=<pk>``, meaningful only alongside the type, selects one
    row of it — the same pairing the model's composite index leads with.

    The filter lives in ``get_queryset`` rather than a ``list`` override on
    purpose: ``ListModelMixin.list`` re-fetches ``self.get_queryset()``, so a
    queryset built inside ``list`` into a local variable is discarded when the
    method delegates to ``super().list`` — the filter would look applied while
    the response still carried every row. Filtering here, after ``super()`` has
    applied the tenant scope, keeps the mixin's isolation intact and reaches the
    queryset ``list`` actually paginates.
    """

    serializer_class = AuditEventSerializer
    queryset = AuditEvent.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        entity_type = self.request.query_params.get("entity_type")
        entity_id = self.request.query_params.get("entity_id")
        if entity_type:
            queryset = queryset.filter(entity_type=entity_type)
            if entity_id:
                queryset = queryset.filter(entity_id=entity_id)
        return queryset
