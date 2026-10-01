"""Tenant resolution middleware and helpers."""
from django.db import connection

TENANT_HEADER = "X-Tenant-Id"
FACILITY_HEADER = "X-Facility-Id"


def set_tenant_context(tenant_id: str, facility_id: str | None = None) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [tenant_id])
        cursor.execute("SELECT set_config('app.facility_id', %s, true)", [facility_id or ""])


def clear_tenant_context() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', '', true)")
        cursor.execute("SELECT set_config('app.facility_id', '', true)")


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_id = request.headers.get(TENANT_HEADER) or request.GET.get("tenant_id")
        facility_id = request.headers.get(FACILITY_HEADER)
        if tenant_id:
            set_tenant_context(str(tenant_id), facility_id)
        else:
            clear_tenant_context()
        return self.get_response(request)
