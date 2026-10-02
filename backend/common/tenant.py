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
from rest_framework.exceptions import PermissionDenied

TENANT_HEADER = "X-Tenant-Id"
FACILITY_HEADER = "X-Facility-Id"

#: Claim names on the access token. Kept as literals here rather than imported
#: from apps.identity_tenancy.tokens so that common/ stays free of app imports -
#: the middleware runs for every request, including ones that never touch a
#: domain app, and an import cycle would be easy to reintroduce.
TENANT_CLAIM = "tenant_id"
FACILITY_CLAIM = "facility_id"

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
    """Tenant and facility as claimed by the request's own headers.

    Used by :class:`TenantMiddleware`, which runs before DRF has authenticated
    anything and therefore cannot see the access token. The signed tenant claims
    are bound later by
    :class:`common.authentication.TenantBoundJWTAuthentication`, which runs
    inside the view and overrides this value.

    Both call sites use :func:`set_tenant_context`, so there is still only one
    mechanism for writing the session setting.
    """
    tenant_id = request.headers.get(TENANT_HEADER) or request.GET.get("tenant_id")
    facility_id = request.headers.get(FACILITY_HEADER)
    return (str(tenant_id) if tenant_id else None, str(facility_id) if facility_id else None)


def bind_tenant(request, tenant_id, facility_id=None) -> None:
    """Record the resolved tenant on the request.

    Called from both entry points so views, mixins and serializers all read the
    same attributes regardless of how the tenant was established.
    """
    setattr(request, REQUEST_TENANT_ATTR, tenant_id)
    setattr(request, REQUEST_FACILITY_ATTR, facility_id)


def bind_tenant_session(tenant_id, facility_id=None) -> None:
    """Bind (or clear) the PostgreSQL tenant session setting.

    Requires the caller to be inside a transaction; see the module docstring.
    """
    if not supports_tenant_guc():
        return
    if tenant_id:
        set_tenant_context(tenant_id, facility_id)
    else:
        clear_tenant_context()


class TenantScopedQuerysetMixin:
    """Scope a DRF viewset's queryset to the request's tenant.

    Applied through ``get_queryset`` rather than per-method overrides, so every
    verb - including the ones DRF generates for detail routes and ``get_object``
    - is covered by one rule.

    This is a second line of defence, not the primary control. Row level
    security in PostgreSQL is what actually enforces isolation; this mixin
    stops unscoped rows being selected in the first place, so a missing policy
    surfaces as an empty queryset rather than a cross-tenant read.

    When no tenant is resolved the queryset is empty rather than unfiltered. An
    unfiltered queryset would be the dangerous failure mode: it would look like
    a working endpoint while returning every tenant's rows.
    """

    #: Field on the model holding the tenant identifier.
    tenant_field = "tenant_id"

    def get_tenant_id(self):
        return getattr(self.request, REQUEST_TENANT_ATTR, None)

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant_id = self.get_tenant_id()
        if not tenant_id:
            return queryset.none()
        return queryset.filter(**{self.tenant_field: tenant_id})

    def perform_create(self, serializer):
        """Stamp the tenant from the request; never trust a client-supplied one."""
        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied(
                "A tenant must be resolved before tenant-owned data can be written."
            )
        serializer.save(**{self.tenant_field: tenant_id})


class TenantMiddleware:
    """Resolve tenant context and bind it for the lifetime of the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_id, facility_id = resolve_tenant(request)
        bind_tenant(request, tenant_id, facility_id)

        if not supports_tenant_guc():
            # The backend has no session settings to bind, so there is nothing
            # for a transaction to scope. Skip it rather than opening a
            # connection on every request: the fast SQLite test suite runs
            # without database access, and this keeps it that way.
            return self.get_response(request)

        with transaction.atomic():
            try:
                bind_tenant_session(tenant_id, facility_id)
                response = self.get_response(request)
            finally:
                # Defence in depth. The transaction-scoped settings are already
                # reset on commit, but clearing explicitly keeps the connection
                # clean for code paths that run outside the atomic block, such
                # as middleware that runs after this one returns.
                clear_tenant_context()

        return response