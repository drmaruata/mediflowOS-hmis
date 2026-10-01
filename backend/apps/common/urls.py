"""Shared, non-tenant-scoped API routes."""
from django.urls import path
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

app_name = "common"


class ApiHealthSerializer(serializers.Serializer):
    """Response contract for the liveness probe."""

    status = serializers.CharField()
    version = serializers.CharField()


class HealthCheckView(APIView):
    """Liveness probe.

    Deliberately anonymous: it must answer before any identity provider is
    reachable. ``authentication_classes`` is empty so a stale or invalid token
    cannot turn a liveness check into a 401, and this is the only view in the
    project permitted to opt out of the deny-by-default permissions set in
    ``REST_FRAMEWORK``.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes: list = []

    @extend_schema(responses=ApiHealthSerializer, auth=[])
    def get(self, request):
        return Response({"status": "ok", "version": "0.1.0"})


urlpatterns = [path("", HealthCheckView.as_view(), name="health")]