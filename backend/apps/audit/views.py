"""Audit views."""
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import AuditEvent
from .serializers import AuditChainVerificationSerializer, AuditEventSerializer
from .services import verify_chain


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

    The viewset stays read-only. The tamper-evidence check is a sub-resource
    (``verify``), not a write: it recomputes the chain from stored rows and
    answers a verdict.
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

    @extend_schema(
        request=None,
        responses={200: AuditChainVerificationSerializer},
        description=(
            "Recompute this tenant's audit hash chain and report the first "
            "row that fails to match (AUD-002). The chain is per tenant and "
            "ordered, so the verdict covers only the caller's own rows. "
            "Rows written before the chain existed carry no digest and are "
            "skipped; a retention purge re-anchors the check on the oldest "
            "surviving row."
        ),
    )
    @action(detail=False, methods=["get"], url_path="verify")
    def verify(self, request):
        """Recompute the tenant's audit hash chain (AUD-002).

        The walk itself lives in :func:`apps.audit.services.verify_chain`
        because it is the same recomputation a scheduler or a CLI repair
        tool would run; the endpoint adds authentication and the tenant scope
        and nothing else. A chain that could only be verified from outside
        the tenant's own rows would not be tamper-evidence — it would be a
        claim someone else had to take on trust.
        """
        result = verify_chain(tenant_id=self.get_tenant_id())
        return Response(AuditChainVerificationSerializer(result).data)
