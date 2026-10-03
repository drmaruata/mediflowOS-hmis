"""OPD views."""
from django.utils import timezone
from rest_framework import serializers as drf_serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import OPDEncounter, Token
from .serializers import OPDEncounterSerializer, TokenSerializer


class TokenViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet[Token]):
    """OPD token management."""
    serializer_class = TokenSerializer
    queryset = Token.objects.all()

    def perform_create(self, serializer: drf_serializers.BaseSerializer[Token]) -> None:
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=False, methods=["get"])
    def queue(self, request: Request) -> Response:
        """Current queue for the authenticated department/doctor."""
        department_id: str | None = request.query_params.get("department_id")
        queryset = self.get_queryset().filter(status="waiting")
        if department_id:
            queryset = queryset.filter(department_id=department_id)
        return Response(TokenSerializer(queryset.order_by("number"), many=True).data)

    @action(detail=True, methods=["post"])
    def call(self, request: Request, pk: str | None = None) -> Response:
        """Call the next token."""
        token: Token = self.get_object()
        token.status = "called"
        token.called_at = timezone.now()
        token.save(update_fields=["status", "called_at"])
        return Response(TokenSerializer(token).data)

    @action(detail=True, methods=["post"])
    def done(self, request: Request, pk: str | None = None) -> Response:
        """Mark token as done."""
        token: Token = self.get_object()
        token.status = "done"
        token.done_at = timezone.now()
        token.save(update_fields=["status", "done_at"])
        return Response(TokenSerializer(token).data)


class OPDEncounterViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet[OPDEncounter]):
    serializer_class = OPDEncounterSerializer
    queryset = OPDEncounter.objects.all()

    def perform_create(self, serializer: drf_serializers.BaseSerializer[OPDEncounter]) -> None:
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
