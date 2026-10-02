"""Liveness and readiness must behave differently, deliberately.

A container healthcheck that depends on PostgreSQL restarts a healthy
application every time the database blips. That was the behaviour before the
health view opted out of ``ATOMIC_REQUESTS``; these tests pin down the split so
it cannot regress into a database-coupled liveness probe.
"""
from unittest import mock

import pytest
from django.db import connection
from django.test import Client
from django.urls import resolve, reverse

pytestmark = pytest.mark.integration

LIVENESS = "/api/v1/health/"
READINESS = "/api/v1/health/ready/"


class TestLiveness:
    def test_answers_without_credentials(self):
        assert Client().get(LIVENESS).status_code == 200

    def test_body_is_the_documented_contract(self):
        response = Client().get(LIVENESS)

        assert response.json() == {"status": "ok", "version": "0.1.0"}

    def test_does_not_touch_the_database(self, monkeypatch):
        """The probe must survive PostgreSQL being unavailable.

        Opening a cursor is the first thing ATOMIC_REQUESTS would do, so this is
        the assertion that catches a reintroduction of the transaction.
        """
        import apps.common.urls as health_urls

        def explode(*args, **kwargs):
            raise AssertionError(
                "the liveness probe must not open a database connection; "
                "a database-coupled healthcheck restarts the container on "
                "every dependency blip"
            )

        monkeypatch.setattr(connection, "cursor", explode)
        monkeypatch.setattr(health_urls, "connection", mock.Mock(cursor=explode))

        assert Client().get(LIVENESS).status_code == 200

    def test_a_bad_token_does_not_break_it(self):
        client = Client(HTTP_AUTHORIZATION="Bearer not-a-real-token")

        assert client.get(LIVENESS).status_code == 200

    def test_reverse_still_resolves(self):
        """Monitoring config usually uses the URL name, not a literal path."""
        assert reverse("common:health") == LIVENESS


class TestReadiness:
    # Readiness genuinely queries the database, so unlike liveness it needs
    # database access.
    pytestmark = pytest.mark.django_db

    def test_reports_ready_when_the_database_answers(self):
        response = Client().get(READINESS)

        assert response.status_code == 200
        assert response.json() == {"status": "ready", "database": "ok"}

    def test_reports_unavailable_rather_than_raising(self):
        """A failed probe should describe the state, not produce a generic 500.

        Conflating "not ready" with "broken" is what makes a load balancer
        restart healthy instances instead of draining them.
        """
        from django.db.utils import OperationalError

        import apps.common.urls as health_urls

        with mock.patch.object(
            health_urls.connection,
            "cursor",
            side_effect=OperationalError("connection refused"),
        ):
            response = Client().get(READINESS)

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["database"] == "unreachable"

    def test_is_still_anonymous(self):
        assert Client().get(READINESS).status_code in (200, 503)


class TestLivenessAndReadinessDiffer:
    def test_readiness_is_a_separate_route(self):
        """Guards against collapsing the two back into one handler."""
        from apps.common.urls import HealthCheckView, ReadinessCheckView

        assert HealthCheckView is not ReadinessCheckView
        assert resolve(LIVENESS).url_name == "health"
        assert resolve(READINESS).url_name == "ready"

    def test_only_the_probes_are_exempt_from_the_request_transaction(self):
        """The exemption is scoped to the two probes, not applied globally.

        Removing ATOMIC_REQUESTS project-wide would break tenant isolation, so
        the point is that only these non-tenant views opt out. The flag is
        checked on the *routed* view, which is where Django looks.
        """
        liveness = resolve(LIVENESS).func
        readiness = resolve(READINESS).func

        assert getattr(liveness, "_non_atomic_requests", set()) == {"default"}
        # Readiness is exempt for a different reason - see its docstring - but
        # it must still not be treated as a tenant-scoped view.
        assert getattr(readiness, "_non_atomic_requests", set()) == {"default"}

    def test_tenant_endpoints_keep_the_transaction(self):
        """The exemption must not have spread to tenant-scoped views."""
        from apps.patient_registry.views import PatientViewSet

        patients = resolve("/api/v1/patients/").func.cls
        assert getattr(patients, "_non_atomic_requests", set()) == set()
        assert PatientViewSet is not None