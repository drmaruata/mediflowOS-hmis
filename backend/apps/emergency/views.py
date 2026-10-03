"""Emergency views."""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import Triage
from .serializers import TriageSerializer


class TriageViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = TriageSerializer
    queryset = Triage.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=False, methods=["get"])
    def tracking_board(self, request):
        """ER tracking board — REST polling, not Channels."""
        status_filter = request.query_params.get("status")
        queryset = self.get_queryset()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return Response(TriageSerializer(queryset.order_by("-arrival_time"), many=True).data)
