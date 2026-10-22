"""MFA enforcement for privileged roles (TEN-006).

The access token carries two claims written by
``TenantAwareTokenSerializer.get_token`` at issuance and copied forward by
refresh rotation: ``requires_mfa`` (the caller's role demands a second factor)
and ``mfa_verified`` (the token was issued with django-otp's verification state
attached; a password-only login yields False). This permission denies a
token-authenticated request when the first is true and the second is not. Both
default to False when absent: an absent ``mfa_verified`` denies, while an absent
``requires_mfa`` simply does not privilege the token, since only tokens this
application issued to a privileged role ever carry it.

Enforcement is a DRF permission rather than Django middleware because middleware
runs outside the view, before ``TenantBoundJWTAuthentication`` has validated the
token, and because the health probe and ABDM callback must be exempt — both set
their own ``permission_classes``.

Installed as the second entry of
``REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]``, after ``IsAuthenticated``:
anonymous requests must fail authentication (401) rather than be told about an
MFA requirement they cannot satisfy. A view declaring its own
``permission_classes`` replaces the defaults wholesale and is not checked here —
the TOTP enrolment endpoints (``TOTPEnrolViewSet``) among them, deliberately, so
an unverified caller can still enrol and confirm a device.
"""
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


class MFARequiredIfConfigured(BasePermission):
    """Deny a token whose role demands MFA but which has not proven it.

    The response body carries ``code = "mfa_required"`` so the frontend can
    route to the MFA challenge instead of showing a generic 403.
    """

    message = (
        "Your role requires multi-factor authentication. "
        "Enrol a TOTP device at /api/v1/mfa-devices/ and confirm it."
    )
    code = "mfa_required"

    def has_permission(self, request, view):
        # Anonymous or unauthenticated requests are handled by IsAuthenticated; this
        # permission only concerns token-authenticated requests, the only ones
        # carrying signed claims. Session-authenticated (browsable API) requests
        # carry no token and pass through.
        auth = getattr(request, "auth", None)
        if auth is None:
            return True

        payload = getattr(auth, "payload", None)
        claims = payload if isinstance(payload, dict) else {}

        requires_mfa = claims.get("requires_mfa", False)
        mfa_verified = claims.get("mfa_verified", False)

        if requires_mfa and not mfa_verified:
            # Raised rather than returned as False: DRF's default exception handler
            # serialises a plain string ``detail`` and drops the error code, and
            # the frontend keys the MFA challenge on that code. A dict detail
            # passes through to the response body unchanged.
            raise PermissionDenied({"detail": self.message, "code": self.code})
        return True
