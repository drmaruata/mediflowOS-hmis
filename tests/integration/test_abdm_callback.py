"""Tests for the ABDM profile-share callback endpoint.

These exist to pin down the current honest state of the endpoint: it is
reachable (so ABDM integration can be developed against it) but it performs
no work and reports 501 rather than a fake success.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.patient_registry.models import ABHACallbackLog


@pytest.mark.integration
def test_abdm_callback_reports_not_implemented():
    """The endpoint must not acknowledge a profile share it has not processed."""
    response = APIClient().post(
        "/api/v1/abdm-callbacks/",
        {
            "request_id": "req-1",
            "facility_abdm_id": "hip-123",
            "status": "ok",
            "profile": {"abha_address": "demo@abha"},
        },
        format="json",
    )

    assert response.status_code == 501
    assert response.json()["status"] == "not_implemented"


@pytest.mark.integration
@pytest.mark.django_db
def test_abdm_callback_writes_nothing():
    """A 501 endpoint must not leave rows behind in the callback log."""
    APIClient().post(
        "/api/v1/abdm-callbacks/",
        {
            "request_id": "req-2",
            "facility_abdm_id": "hip-123",
            "status": "ok",
        },
        format="json",
    )

    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
def test_abdm_callback_is_anonymous_by_design():
    """The ABDM gateway carries no user JWT, so this route must stay open.

    This is the one place an anonymous write endpoint is intentional. It is
    safe only because it is non-functional; if it ever starts processing
    payloads it must authenticate the gateway first.
    """
    response = APIClient().post(
        "/api/v1/abdm-callbacks/", {"request_id": "req-3"}, format="json"
    )

    assert response.status_code == 501


@pytest.mark.integration
def test_health_probe_route_name_is_stable():
    """Guard against a router rename silently breaking monitoring."""
    assert reverse("common:health") == "/api/v1/health/"