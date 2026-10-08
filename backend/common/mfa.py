"""MFA enforcement for privileged roles (TEN-006).

The access token carries two claims relevant here; both are written by
``TenantAwareTokenSerializer.get_token`` at issuance and survive refresh
(rotation copies them forward), so a token judged here always carries them:

* ``requires_mfa`` — the caller's role demands a second factor.
* ``mfa_verified`` — the token was issued with django-otp's verification
  state attached (``user.otp_device``); a password-only login yields False.

This permission class denies a token-authenticated request when
``requires_mfa`` is true and ``mfa_verified`` is not. Each claim defaults to
False when absent: an absent ``mfa_verified`` therefore denies, while an
absent ``requires_mfa`` simply does not privilege the token — only tokens
this application issued to a privileged role ever carry it. The denial
carries ``code = "mfa_required"`` so the frontend can route to the MFA
challenge instead of showing a generic 403.

Enforcement is a DRF permission rather than Django middleware because:

1. DRF middleware runs outside the view transaction, where the token has not
   yet been validated by ``TenantBoundJWTAuthentication``.
2. A permission class runs inside the view, after authentication, so the claims
   are reliably available.
3. The health probe and ABDM callback must be exempt — both set their own
   ``permission_classes``, so a default-installed permission is the cleanest
   approach.

Installed as the second entry of
``REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]``, after ``IsAuthenticated``:
anonymous requests must fail authentication (401) rather than be told about
an MFA requirement they cannot satisfy. A view that declares its own
``permission_classes`` replaces the defaults wholesale and is therefore not
checked here — the TOTP enrolment endpoints (``TOTPEnrolViewSet``) among
them, deliberately, so an unverified caller can still enrol and confirm a
device.
"""
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


class MFARequiredIfConfigured(BasePermission):
    """Deny a token whose role demands MFA but which has not proven it.

    Returns a clear message, and the response body carries
    ``code = "mfa_required"`` alongside it so the frontend can distinguish
    this 403 from every other one.
    """

    message = (
        "Your role requires multi-factor authentication. "
        "Enrol a TOTP device at /api/v1/mfa-devices/ and confirm it."
    )
    code = "mfa_required"

    def has_permission(self, request, view):
        # Anonymous or unauthenticated requests are handled by IsAuthenticated;
        # this permission only concerns token-authenticated requests, which are
        # the only ones carrying signed claims to read. Session-authenticated
        # requests (browsable API) carry no token and pass through.
        auth = getattr(request, "auth", None)
        if auth is None:
            return True

        payload = getattr(auth, "payload", None)
        claims = payload if isinstance(payload, dict) else {}

        requires_mfa = claims.get("requires_mfa", False)
        mfa_verified = claims.get("mfa_verified", False)

        if requires_mfa and not mfa_verified:
            # Raised rather than returned as False: DRF's default exception
            # handler serialises a plain string ``detail`` and drops the error
            # code, and the frontend keys the MFA challenge on that code. A
            # dict detail is passed through to the response body unchanged.
            raise PermissionDenied({"detail": self.message, "code": self.code})
        return True
