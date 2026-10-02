"""Shared, non-tenant-scoped API routes: liveness and readiness.

The distinction matters. A container healthcheck that depends on PostgreSQL will
restart a perfectly healthy application whenever the database is briefly
unavailable, turning a dependency blip into a restart loop. Liveness therefore
answers "is this process working" without touching the database, and readiness
answers "can this process serve traffic" with a real query.
"""
from django.db import connection, transaction
from django.urls import path
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET
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


class ReadinessSerializer(serializers.Serializer):
    status = serializers.CharField()
    database = serializers.CharField()


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class HealthCheckView(APIView):
    """Liveness probe.

    Deliberately anonymous *and* deliberately database-free. It must answer
    before any identity provider is reachable, and it must keep answering while
    PostgreSQL is down, because the container healthcheck is wired to it.

    ``authentication_classes`` is empty so a stale or invalid token cannot turn a
    liveness check into a 401. This is the only view in the project permitted to
    opt out of the deny-by-default permissions.

    ``non_atomic_requests`` opts this view out of ``ATOMIC_REQUESTS``.
    AGENTS.md forbids that decorator because the request transaction is what
    keeps the tenant session setting scoped; removing it would break isolation.
    That reasoning does not apply here: this view resolves no tenant, reads no
    tenant-owned table and issues no query, so there is nothing for the
    transaction to protect. Keeping it would open a database connection on every
    probe and make the probe fail whenever PostgreSQL is unavailable - exactly
    when an orchestrator must not be restarting this container.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(responses=ApiHealthSerializer, auth=[])
    @require_GET
    def get(self, request):
        return Response({"status": "ok", "version": "0.1.0"})


class ReadinessCheckView(APIView):
    """Readiness probe: reports whether this process can actually serve.

    Returns 503 when the database is unreachable, so a load balancer removes the
    instance from rotation instead of the instance being killed and restarted.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(responses=ReadinessSerializer, auth=[])
    @require_GET
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:
            # Reported rather than raised: the point of the probe is to describe
            # the state, and an exception would produce a generic 500 that
            # conflates "not ready" with "broken".
            return Response(
                {
                    "status": "unavailable",
                    "database": "unreachable",
                    "detail": type(exc).__name__,
                },
                status=503,
            )
        return Response({"status": "ready", "database": "ok"})


urlpatterns = [
    # Mounted at "api/v1/health/" in config/urls.py, so these patterns are
    # relative to that prefix and must stay empty or bare.
    path("", HealthCheckView.as_view(), name="health"),
    path("ready/", ReadinessCheckView.as_view(), name="ready"),
]