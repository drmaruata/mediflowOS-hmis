"""Tenant context resolution.

Tenant context is a pair of PostgreSQL session settings, ``app.tenant_id``
and ``app.facility_id``, that row level security policies read to decide which
rows a statement may touch (architecture doc, section 7).

The setting must be established *inside* the transaction that runs the
request's queries. ``set_config(name, value, is_local=true)`` is
transaction-scoped: if it is issued while the connection is in autocommit mode
the implicit single-statement transaction commits immediately and the value is
discarded, so subsequent queries see no tenant context. Issuing it from
middleware outside a transaction therefore silently disables isolation.

:class:`TenantMiddleware` opens the transaction and sets the value inside it,
and ``ATOMIC_REQUESTS`` keeps the view inside that same transaction.
"""
from django.db import connection, transaction

TENANT_HEADER = "X-Tenant-Id"
FACILITY_HEADER = "X-Facility-Id"

TENANT_SETTING = "app.tenant_id"
FACILITY_SETTING = "app.facility_id"

# Attribute names used to expose the resolved context on the request.
REQUEST_TENANT_ATTR = "tenant_id"
REQUEST_FACILITY_ATTR = "facility_id"


def supports_tenant_guc() -> bool:
    """Whether the active backend can hold the tenant session settings.

    Only PostgreSQL has ``set_config``. SQLite is used for the fast unit and
    integration suite, where tenant context is tracked on the request instead.
    """
    return connection.vendor == "postgresql"


def set_tenant_context(tenant_id: str, facility_id: str | None = None) -> None:
    """Bind tenant and facility to the current transaction."""
    if not supports_tenant_guc():
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, true)", [TENANT_SETTING, tenant_id])
        cursor.execute(
            "SELECT set_config(%s, %s, true)", [FACILITY_SETTING, facility_id or ""]
        )


def clear_tenant_context() -> None:
    """Drop tenant and facility for the remainder of the transaction."""
    if not supports_tenant_guc():
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, '', true)", [TENANT_SETTING])
        cursor.execute("SELECT set_config(%s, '', true)", [FACILITY_SETTING])


def resolve_tenant(request) -> tuple[str | None, str | None]:
    """Read tenant and facility identifiers from headers.

    ``tenant_id`` is also accepted as a query parameter because ABDM gateway
    callbacks are constructed by external software that cannot always set
    custom headers.
    """
    tenant_id = request.headers.get(TENANT_HEADER) or request.GET.get("tenant_id")
    facility_id = request.headers.get(FACILITY_HEADER)
    return (str(tenant_id) if tenant_id else None, str(facility_id) if facility_id else None)


class TenantMiddleware:
    """Resolve tenant context and bind it for the lifetime of the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_id, facility_id = resolve_tenant(request)

        setattr(request, REQUEST_TENANT_ATTR, tenant_id)
        setattr(request, REQUEST_FACILITY_ATTR, facility_id)

        if not supports_tenant_guc():
            # The backend has no session settings to bind, so there is nothing
            # for a transaction to scope. Skip it rather than opening a
            # connection on every request: the fast SQLite test suite runs
            # without database access, and this keeps it that way.
            return self.get_response(request)

        with transaction.atomic():
            try:
                if tenant_id:
                    set_tenant_context(tenant_id, facility_id)
                else:
                    clear_tenant_context()
                response = self.get_response(request)
            finally:
                # Defence in depth. The transaction-scoped settings are already
                # reset on commit, but clearing explicitly keeps the connection
                # clean for code paths that run outside the atomic block, such
                # as middleware that runs after this one returns.
                clear_tenant_context()

        return response