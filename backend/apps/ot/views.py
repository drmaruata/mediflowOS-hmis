"""OT views."""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import OperationSchedule, SurgeryRecord
from .serializers import OperationScheduleSerializer, SurgeryRecordSerializer


class OperationScheduleViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = OperationScheduleSerializer
    queryset = OperationSchedule.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=False, methods=["get"])
    def conflicts(self, request):
        """Detect scheduling conflicts."""
        date = request.query_params.get("date")
        queryset = self.get_queryset()
        if date:
            queryset = queryset.filter(scheduled_start__date=date)
        return Response(OperationScheduleSerializer(queryset, many=True).data)


class SurgeryRecordViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = SurgeryRecordSerializer
    queryset = SurgeryRecord.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
