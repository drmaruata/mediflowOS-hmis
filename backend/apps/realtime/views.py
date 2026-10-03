"""Realtime views."""
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet


class RealtimeStatusViewSet(ViewSet):
    """Realtime subscription status.

    Lists the WebSocket channel groups the user is authorized to join,
    scoped to their tenant and facility.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=inline_serializer(
            "RealtimeSubscription",
            fields={
                "tenant_id": serializers.UUIDField(allow_null=True),
                "facility_id": serializers.UUIDField(allow_null=True),
                "channels": serializers.ListField(child=serializers.CharField()),
                "protocol": serializers.CharField(),
            },
        )
    )
    @action(detail=False, methods=["get"])
    def subscription(self, request):
        """Returns the tenant-scoped channel groups for this user."""
        tenant_id = getattr(request, "tenant_id", None)
        facility_id = getattr(request, "facility_id", None)
        return Response({
            "tenant_id": tenant_id,
            "facility_id": facility_id,
            "channels": [
                f"tenant_{tenant_id}",
                f"vitals_{tenant_id}",
            ],
            "protocol": "ws",
        })
