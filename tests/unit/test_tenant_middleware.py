"""Unit tests for tenant context resolution.

The original version of this file asserted only that the middleware forwarded
header values to ``set_tenant_context``. That test passed even though the
mechanism was broken: ``set_config(..., is_local=true)`` was issued outside any
transaction, so PostgreSQL discarded it before any tenant-owned query ran. The
tests below pin down the transaction coupling that fixes it, without requiring
a live PostgreSQL server.
"""
import pytest
from django.http import HttpResponse
from django.test import RequestFactory

import common.tenant as tenant


def _request(path="/resource/", **headers):
    return RequestFactory().get(path, **headers)


@pytest.mark.unit
class TestResolveTenant:
    def test_reads_tenant_and_facility_headers(self):
        request = _request(
            HTTP_X_TENANT_ID="tenant-1",
            HTTP_X_FACILITY_ID="facility-1",
        )

        assert tenant.resolve_tenant(request) == ("tenant-1", "facility-1")

    def test_falls_back_to_query_parameter(self):
        """ABDM callbacks are external software and may not set headers."""
        request = _request("/resource/?tenant_id=tenant-9")

        assert tenant.resolve_tenant(request) == ("tenant-9", None)

    def test_header_wins_over_query_parameter(self):
        request = _request("/resource/?tenant_id=from-query", HTTP_X_TENANT_ID="from-header")

        assert tenant.resolve_tenant(request)[0] == "from-header"

    def test_absent_context_is_none(self):
        assert tenant.resolve_tenant(_request()) == (None, None)


@pytest.mark.unit
@pytest.mark.django_db
class TestMiddlewareBinding:
    """The binding path, with the vendor guard forced on.

    These need database access because the middleware genuinely opens a
    transaction: that coupling is precisely what is under test.
    """

    @pytest.fixture(autouse=True)
    def _pretend_postgres(self, monkeypatch):
        monkeypatch.setattr(tenant, "supports_tenant_guc", lambda: True)

    def test_binds_tenant_and_facility_inside_a_transaction(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            tenant,
            "set_tenant_context",
            lambda tenant_id, facility_id=None: calls.append(("set", tenant_id, facility_id)),
        )
        monkeypatch.setattr(
            tenant, "clear_tenant_context", lambda: calls.append(("clear",))
        )
        middleware = tenant.TenantMiddleware(lambda request: HttpResponse("ok"))

        response = middleware(
            _request(HTTP_X_TENANT_ID="tenant-1", HTTP_X_FACILITY_ID="facility-1")
        )

        assert response.status_code == 200
        # Bound on the way in, and explicitly cleared on the way out so the
        # connection cannot carry the tenant into the next request.
        assert calls == [
            ("set", "tenant-1", "facility-1"),
            ("clear",),
        ]

    def test_clears_when_no_tenant_is_supplied(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            tenant, "set_tenant_context", lambda *a, **k: calls.append(("set",))
        )
        monkeypatch.setattr(
            tenant, "clear_tenant_context", lambda: calls.append(("clear",))
        )
        middleware = tenant.TenantMiddleware(lambda request: HttpResponse("ok"))

        middleware(_request())

        assert calls == [("clear",), ("clear",)]

    def test_context_is_cleared_even_when_the_view_raises(self, monkeypatch):
        """A failing request must not leak tenant context to the next one."""
        calls = []
        monkeypatch.setattr(
            tenant, "set_tenant_context", lambda *a, **k: calls.append("set")
        )
        monkeypatch.setattr(
            tenant, "clear_tenant_context", lambda: calls.append("clear")
        )

        def boom(request):
            raise RuntimeError("view failed")

        middleware = tenant.TenantMiddleware(boom)

        with pytest.raises(RuntimeError):
            middleware(_request(HTTP_X_TENANT_ID="tenant-1"))

        assert calls == ["set", "clear"]

    def test_exposes_context_on_the_request(self, monkeypatch):
        # The binding helpers are stubbed because this test only asserts the
        # attributes the middleware puts on the request. Letting them run for
        # real would issue PostgreSQL's set_config against SQLite.
        monkeypatch.setattr(tenant, "set_tenant_context", lambda *a, **k: None)
        monkeypatch.setattr(tenant, "clear_tenant_context", lambda: None)

        seen = {}

        def view(request):
            seen["tenant_id"] = request.tenant_id
            seen["facility_id"] = request.facility_id
            return HttpResponse("ok")

        middleware = tenant.TenantMiddleware(view)
        response = middleware(
            _request(HTTP_X_TENANT_ID="tenant-1", HTTP_X_FACILITY_ID="facility-1")
        )

        assert response.status_code == 200
        assert seen == {"tenant_id": "tenant-1", "facility_id": "facility-1"}


@pytest.mark.unit
class TestMiddlewareWithoutGucSupport:
    """On a backend with no session settings there is nothing to scope."""

    @pytest.fixture(autouse=True)
    def _pretend_no_guc(self, monkeypatch):
        monkeypatch.setattr(tenant, "supports_tenant_guc", lambda: False)

    def test_does_not_open_a_transaction_or_touch_the_database(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("middleware must not touch the database here")

        monkeypatch.setattr(tenant, "set_tenant_context", explode)
        monkeypatch.setattr(tenant, "clear_tenant_context", explode)
        seen = {}

        def view(request):
            seen["tenant_id"] = request.tenant_id
            seen["facility_id"] = request.facility_id
            return HttpResponse("ok")

        response = tenant.TenantMiddleware(view)(
            _request(HTTP_X_TENANT_ID="tenant-1", HTTP_X_FACILITY_ID="facility-1")
        )

        assert response.status_code == 200
        # Resolution still happens, so views can read the tenant off the
        # request even where the GUC is unavailable.
        assert seen == {"tenant_id": "tenant-1", "facility_id": "facility-1"}