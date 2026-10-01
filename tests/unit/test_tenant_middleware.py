import pytest
from django.http import HttpResponse
from django.test import RequestFactory

import common.tenant as tenant


@pytest.mark.unit
def test_tenant_middleware_uses_tenant_and_facility_headers(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tenant,
        "set_tenant_context",
        lambda tenant_id, facility_id=None: calls.append((tenant_id, facility_id)),
    )
    request = RequestFactory().get(
        "/resource/",
        HTTP_X_TENANT_ID="tenant-1",
        HTTP_X_FACILITY_ID="facility-1",
    )
    middleware = tenant.TenantMiddleware(lambda request: HttpResponse("ok"))

    response = middleware(request)

    assert response.status_code == 200
    assert calls == [("tenant-1", "facility-1")]


@pytest.mark.unit
def test_tenant_middleware_clears_context_without_tenant(monkeypatch):
    calls = []
    monkeypatch.setattr(tenant, "clear_tenant_context", lambda: calls.append("cleared"))
    request = RequestFactory().get("/resource/")
    middleware = tenant.TenantMiddleware(lambda request: HttpResponse("ok"))

    response = middleware(request)

    assert response.status_code == 200
    assert calls == ["cleared"]