"""MFA enforcement for privileged roles (TEN-006).

The JWT token carries two claims relevant here:

* ``mfa_verified`` — whether the user has a confirmed TOTP device.
* ``requires_mfa`` — whether the user's role demands a second factor.

This permission class blocks access when the role requires MFA but the user has
not enrolled and confirmed a TOTP device. It runs after authentication, so the
signed claims are available.

Enforcement is a DRF permission rather than Django middleware because:

1. DRF middleware runs outside the view transaction, where the token has not
   yet been validated by ``TenantBoundJWTAuthentication``.
2. A permission class runs inside the view, after authentication, so the claims
   are reliably available.
3. The health probe and ABDM callback must be exempt — both set their own
   ``permission_classes``, so a default-installed permission is the cleanest
   approach.

This is added to ``REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`` alongside
``IsAuthenticated``, so every authenticated endpoint enforces it automatically.
Endpoints that opt out of authentication (health probe, ABDM callback) also
opt out of this.
"""
from rest_framework.permissions import BasePermission


class MFARequiredIfConfigured(BasePermission):
    """Deny access when the role requires MFA but the user has not enrolled.

    Returns a clear message so the frontend can prompt for TOTP setup instead
    of showing a generic 403.
    """

    message = (
        "Your role requires multi-factor authentication. "
        "Enrol a TOTP device at /api/v1/mfa-devices/ and confirm it."
    )

    def has_permission(self, request, view):
        # Anonymous or unauthenticated requests are handled by IsAuthenticated;
        # this permission only concerns authenticated users.
        auth = getattr(request, "auth", None)
        if auth is None:
            return True

        payload = getattr(auth, "payload", None)
        claims = payload if isinstance(payload, dict) else {}

        requires_mfa = claims.get("requires_mfa", False)
        mfa_verified = claims.get("mfa_verified", False)

        if requires_mfa and not mfa_verified:
            return False
        return True
