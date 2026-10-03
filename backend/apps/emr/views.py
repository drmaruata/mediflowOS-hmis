"""EMR views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import ClinicalDocument, ProblemList, SafetyEvent
from .serializers import ClinicalDocumentSerializer, ProblemListSerializer, SafetyEventSerializer


class ClinicalDocumentViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = ClinicalDocumentSerializer
    queryset = ClinicalDocument.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=True, methods=["post"])
    def amend(self, request, pk=None):
        """Amend a clinical document (append-only versioning)."""
        doc = self.get_object()
        new_version = ClinicalDocument.objects.create(
            tenant_id=doc.tenant_id,
            patient_id=doc.patient_id,
            doc_type=doc.doc_type,
            content=request.data.get("content", doc.content),
            version=doc.version + 1,
            amended_from=doc.id,
            created_by=getattr(request.user, "pk", None),
        )
        return Response(ClinicalDocumentSerializer(new_version).data, status=status.HTTP_201_CREATED)


class ProblemListViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = ProblemListSerializer
    queryset = ProblemList.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})


class SafetyEventViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = SafetyEventSerializer
    queryset = SafetyEvent.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
