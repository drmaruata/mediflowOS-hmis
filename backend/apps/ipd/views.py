"""IPD views."""
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import Admission, BedStatus, CensusSnapshot
from .serializers import AdmissionSerializer, BedStatusSerializer, CensusSnapshotSerializer


class AdmissionViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = AdmissionSerializer
    queryset = Admission.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=True, methods=["post"])
    def discharge(self, request, pk=None):
        """Discharge an admission with mandatory disposition."""
        admission = self.get_object()
        disposition = request.data.get("disposition")
        if not disposition:
            return Response(
                {"disposition": "Discharge disposition is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        admission.discharged_at = timezone.now()
        admission.disposition = disposition
        admission.discharge_summary = request.data.get("discharge_summary", "")
        admission.save(update_fields=["discharged_at", "disposition", "discharge_summary"])
        return Response(AdmissionSerializer(admission).data)

    @action(detail=False, methods=["get"])
    def active(self, request):
        """List active admissions for the tenant."""
        queryset = self.get_queryset().filter(discharged_at__isnull=True)
        return Response(AdmissionSerializer(queryset, many=True).data)


class BedStatusViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = BedStatusSerializer
    queryset = BedStatus.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=False, methods=["get"])
    def board(self, request):
        """Live bed board, optionally narrowed to one ward.

        Scoped by ``ward_id``, not ``facility_id``: BedStatus has no facility
        column, because a bed belongs to a ward and the ward already resolves to
        a department and facility. Filtering on a column that does not exist
        raises FieldError, which surfaced as a 500 on the bed board.
        """
        ward_id = request.query_params.get("ward_id")
        queryset = self.get_queryset()
        if ward_id:
            queryset = queryset.filter(ward_id=ward_id)
        return Response(BedStatusSerializer(queryset, many=True).data)


class CensusSnapshotViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = CensusSnapshotSerializer
    queryset = CensusSnapshot.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
