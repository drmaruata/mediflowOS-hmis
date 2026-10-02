"""Authentication that binds the tenant from a signed credential.

Why this is a separate step from :class:`common.tenant.TenantMiddleware`
----------------------------------------------------------------------
The Django middleware runs before DRF has validated the access token, so it
cannot know who is calling and must fall back to the ``X-Tenant-Id`` header.
That header is client-supplied, and an earlier version of this project let it
decide the tenant for *every* request - including authenticated ones. Any
logged-in user could therefore read another hospital's rows by changing a
header, and because the same header fed the row level security policy, the
database filtered for the caller's chosen tenant rather than their own.

DRF authenticates inside the view, which is still inside the request
transaction, so the tenant setting can be rebound there from the token's signed
claims. The token therefore wins over the header, and a token without a tenant
claim clears the context rather than falling back.

Both this class and the middleware call ``common.tenant.set_tenant_context``,
so there remains exactly one mechanism for writing the PostgreSQL session
setting - only the inputs differ, because the two entry points genuinely have
different trust properties:

* the header path serves the ABDM gateway callback and internal service calls,
  which carry no user JWT;
* the token path serves every authenticated user request.
"""
from rest_framework_simplejwt.authentication import JWTAuthentication

from .tenant import (
    FACILITY_CLAIM,
    TENANT_CLAIM,
    bind_tenant,
    bind_tenant_session,
)


class TenantBoundJWTAuthentication(JWTAuthentication):
    """Validates the token, then binds its tenant claims to the request."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            # No credentials presented. Leave whatever the middleware resolved
            # alone, so the ABDM callback and service-to-service paths keep
            # working.
            return result

        user, token = result
        payload = getattr(token, "payload", None)
        claims = payload if isinstance(payload, dict) else {}

        tenant_id = claims.get(TENANT_CLAIM)
        facility_id = claims.get(FACILITY_CLAIM)

        # A token with no tenant claim is a real account with no active
        # membership. Clearing the context is deliberate: falling back to the
        # header would hand such a user access to an arbitrary tenant.
        bind_tenant(request, str(tenant_id) if tenant_id else None,
                    str(facility_id) if facility_id else None)
        bind_tenant_session(
            str(tenant_id) if tenant_id else None,
            str(facility_id) if facility_id else None,
        )
        return result


def claims_from(request) -> dict:
    """The validated token's claims for the current request.

    Reads ``auth.payload`` rather than treating the token as a mapping.
    djangorestframework-simplejwt 5.x made ``Token`` a plain class, not a
    ``dict`` subclass, so an ``isinstance(token, dict)`` check silently
    evaluates false and every claim reads as absent. That failure is quiet:
    nothing raises, the role simply comes back as None. Reading ``payload``
    directly is what actually works.
    """
    auth = getattr(request, "auth", None)
    payload = getattr(auth, "payload", None)
    return payload if isinstance(payload, dict) else {}