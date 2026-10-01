import pytest
from rest_framework.test import APIClient


@pytest.mark.integration
def test_health_endpoint_returns_service_status():
    response = APIClient().get("/api/v1/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}