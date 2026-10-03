"""Blood Bank views."""
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import BloodComponent, CrossMatch, Donation, Donor, Requisition, TransfusionReaction
from .serializers import (
    BloodComponentSerializer, CrossMatchSerializer, DonationSerializer,
    DonorSerializer, RequisitionSerializer, TransfusionReactionSerializer,
)


class DonorViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = DonorSerializer
    queryset = Donor.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})


class DonationViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = DonationSerializer
    queryset = Donation.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})


class BloodComponentViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = BloodComponentSerializer
    queryset = BloodComponent.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})


class RequisitionViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = RequisitionSerializer
    queryset = Requisition.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        """Issue a blood component."""
        requisition = self.get_object()
        requisition.issued_at = timezone.now()
        requisition.source = request.data.get("source", requisition.source)
        requisition.save(update_fields=["issued_at", "source"])
        return Response(RequisitionSerializer(requisition).data)


class CrossMatchViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = CrossMatchSerializer
    queryset = CrossMatch.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})


class TransfusionReactionViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = TransfusionReactionSerializer
    queryset = TransfusionReaction.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
