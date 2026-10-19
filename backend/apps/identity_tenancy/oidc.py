"""OIDC single sign-on: exchange an IdP-issued ID token for the local pair (INT-009).

Security model
--------------
The IdP's signature is the root of trust. ``POST /api/v1/auth/oidc/`` verifies
issuer, audience, signature AND expiry against the IdP's published JWKS before
anything local happens — no row is read, written or provisioned for a token
that failed any of the four, and a token carrying no ``exp`` is refused rather
than verified forever. The tenant claim is trusted only because it arrives
inside that verified token, never because it is secret, and it is looked up as
a tenant **slug** so a human can audit which tenant a login bound — never a raw
UUID taken from the token. An absent or unresolvable claim refuses with 403;
there is no default-tenant fallback.

No local password is ever set for an OIDC-provisioned account
(:meth:`set_unusable_password`), so an OIDC identity cannot be replayed against
``auth/token/`` as a password guess.

This endpoint is anonymous on the same terms as ``auth/token/``: it IS the
credential-issuing path, and the caller's authentication is the verified IdP
signature on the token it presents, not a bearer header.

Settings (declared in ``config/settings/base.py``):

* ``OIDC_ISSUER`` / ``OIDC_AUDIENCE`` / ``OIDC_JWKS_URI`` — the required trio.
  Any absent and the endpoint answers 501 with a structured body before the
  request body is even parsed, so an unconfigured deployment does zero
  cryptographic work and touches zero rows — never a fake 200.
* ``OIDC_TENANT_CLAIM`` — the ID-token claim carrying the tenant slug;
  defaults to ``tenant``.
* ``OIDC_JIT_PROVISION`` — opt-in just-in-time provisioning; default false,
  an unknown identity is refused with 403 while it is off. When on, a new
  account gets an unusable password and one active membership on the bound
  tenant in the deliberately empty-permission ``SSO User`` role. A role by that
  name that has been given permissions, MFA or break-glass is refused (403)
  rather than adopted, because a login must never be a role-granting event;
  an operator who wants privileged SSO users grants the membership up front.

The exchange issues through the same serializer as the password flow
(``TenantAwareTokenSerializer``), so the pair is identical in shape and claims.
Because that serializer binds the account's active membership, and this
endpoint must bind exactly the tenant the sign-on named, an account whose
active membership resolves to another tenant is refused rather than issued a
token for a tenant the token did not name.
"""
import logging

import httpx
import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.settings import api_settings

from .models import Role, Tenant, UserMembership
from .tokens import (
    FACILITY_CLAIM,
    MFA_CLAIM,
    PERMISSIONS_CLAIM,
    REQUIRES_MFA_CLAIM,
    ROLE_CLAIM,
    TENANT_CLAIM,
    TenantAwareTokenSerializer,
    active_membership,
)

logger = logging.getLogger(__name__)

#: Clock-skew tolerance handed to ``jwt.decode``'s ``leeway``, so an IdP
#: running slightly ahead does not refuse honest logins. Expiry is still
#: enforced: ``exp`` is a required claim (``REQUIRED_CLAIMS`` below).
LEEWAY_SECONDS = 30

#: The least-privilege role a just-in-provisioned account is enrolled in. A
#: tenant-authored role by this name is adopted only while it holds no
#: permissions, MFA requirement or break-glass — adopting a privileged one
#: would make every login a role grant.
JIT_ROLE_NAME = "SSO User"

#: OIDC Core's mandatory ID-token claims. Without ``exp`` in the list a token
#: carrying no expiry would verify forever.
REQUIRED_CLAIMS = ("exp", "iss", "aud", "sub")

NO_TENANT_MESSAGE = "The identity token does not name a tenant this deployment hosts."
NO_ACCOUNT_MESSAGE = "No account on that tenant matches this identity."
INVALID_TOKEN_MESSAGE = "The identity token failed verification."
IDP_UNAVAILABLE_MESSAGE = "The identity provider's signing keys could not be retrieved."
NOT_CONFIGURED_MESSAGE = (
    "OIDC single sign-on is not configured. Set OIDC_ISSUER, OIDC_AUDIENCE and "
    "OIDC_JWKS_URI in the environment."
)


class _ExchangeRefused(Exception):
    """A verified identity that may not log in to the bound tenant."""

    def __init__(self, message=NO_ACCOUNT_MESSAGE):
        self.message = message
        super().__init__(message)


def fetch_jwks(jwks_uri: str) -> dict:
    """Fetch the IdP's JWKS document.

    The one I/O seam: tests replace this with a stub returning the JWKS dict,
    so the suite pins key selection and signature verification without a
    network. Transport and parse failures propagate to the view, which maps
    them to 503 — an unreachable IdP is an integration failure, not a verdict
    on the caller's token.
    """
    response = httpx.get(jwks_uri, timeout=10.0)
    response.raise_for_status()
    return response.json()


def _matching_jwk(jwks, kid):
    """The JWK that verifies this token, or ``None`` when the set has none.

    A ``kid``-less token is only verifiable against a single-key set: guessing
    between keys would verify nothing. Non-dict entries in a hostile or broken
    key set are ignored rather than crashed on.
    """
    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    if not isinstance(keys, list):
        return None
    keys = [key for key in keys if isinstance(key, dict)]
    if kid is None:
        return keys[0] if len(keys) == 1 else None
    return next((key for key in keys if key.get("kid") == kid), None)


def verify_id_token(id_token: str) -> dict:
    """Verify the ID token's signature, issuer, audience and expiry (INT-009).

    Only ``jwt.PyJWTError`` escapes for a bad token and only
    ``(httpx.HTTPError, ValueError)`` for an unusable key set, so the view can
    map failures to 401 and 503 without inspecting exception types.
    """
    header = jwt.get_unverified_header(id_token)
    jwks = fetch_jwks(settings.OIDC_JWKS_URI)
    jwk = _matching_jwk(jwks, header.get("kid"))
    if jwk is None:
        raise jwt.InvalidTokenError("no key in the IdP's JWKS matches this token")
    key = jwt.PyJWK(jwk)
    return jwt.decode(
        id_token,
        key=key.key,
        algorithms=["RS256"],
        audience=settings.OIDC_AUDIENCE,
        issuer=settings.OIDC_ISSUER,
        leeway=LEEWAY_SECONDS,
        options={"require": list(REQUIRED_CLAIMS)},
    )


def _resolve_user(claims, tenant):
    """The local account for this verified identity, provisioned if allowed.

    Existing accounts are matched by the ``email`` claim and by ``sub`` (the
    provisioned username), so a provisioned user is found again on their next
    sign-on even when their token carries no email. Every refusal below raises
    the same stable message, so the endpoint cannot distinguish — for a caller
    — an unknown identity from an ambiguous one from a disabled one, and cannot
    be used to enumerate accounts.
    """
    UserModel = get_user_model()
    email = str(claims.get("email") or "").strip()
    sub = str(claims.get("sub") or "").strip()
    matches = set()
    if email:
        matches.update(UserModel.objects.filter(email__iexact=email))
    if sub:
        matches.update(UserModel.objects.filter(username__iexact=sub))
    if len(matches) == 1:
        return matches.pop()
    if matches or not settings.OIDC_JIT_PROVISION or not sub:
        # More than one match is an ambiguity the endpoint must not resolve by
        # guessing; zero matches falls through to provisioning only when the
        # operator opted in and `sub` is present to name the account.
        raise _ExchangeRefused()
    if len(sub) > UserModel._meta.get_field("username").max_length:
        # Truncating instead would risk two long subjects colliding into one
        # account, which is an identity merge, not a login.
        raise _ExchangeRefused()
    with transaction.atomic():
        # The role is resolved first: a tenant-authored "SSO User" role found
        # to be privileged aborts before the account exists, and the raise
        # rolls the block back if anything did land.
        role = Role.objects.get_or_create(
            tenant=tenant, name=JIT_ROLE_NAME, defaults={"permissions": []}
        )[0]
        if role.permissions or role.require_mfa or role.allows_break_glass:
            logger.warning(
                "OIDC exchange refused: the %r role on tenant %s holds "
                "privileges; refusing to enrol a provisioned account in it",
                JIT_ROLE_NAME, tenant.slug,
            )
            raise _ExchangeRefused()
        try:
            user = UserModel(username=sub, email=email)
            user.set_unusable_password()
            user.save()
            UserMembership.objects.create(
                user=user, tenant=tenant, role=role, active=True
            )
        except IntegrityError as error:
            # A concurrent first sign-on claimed the username; the loser is
            # refused, and their retry matches the account that won.
            raise _ExchangeRefused() from error
    return user


class OIDCExchangeRequestSerializer(serializers.Serializer):
    id_token = serializers.CharField()


_OIDCExchangeResponse = inline_serializer(
    "OIDCExchangeResponse",
    fields={
        "refresh": serializers.CharField(),
        "access": serializers.CharField(),
        MFA_CLAIM: serializers.BooleanField(),
        TENANT_CLAIM: serializers.UUIDField(allow_null=True),
        FACILITY_CLAIM: serializers.UUIDField(allow_null=True),
        ROLE_CLAIM: serializers.CharField(allow_null=True),
        PERMISSIONS_CLAIM: serializers.ListField(child=serializers.CharField()),
        REQUIRES_MFA_CLAIM: serializers.BooleanField(),
    },
)


class OIDCTokenExchangeView(APIView):
    """Exchanges a verified OIDC ID token for the local token pair (INT-009).

    The security model this view enforces is stated in the module docstring;
    only the ordering is visible here — the configuration check runs before
    ``request.data`` is touched, so an unconfigured deployment answers 501
    having done no work at all.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["auth"],
        request=OIDCExchangeRequestSerializer,
        responses={200: _OIDCExchangeResponse},
    )
    def post(self, request):
        if not (
            settings.OIDC_ISSUER
            and settings.OIDC_AUDIENCE
            and settings.OIDC_JWKS_URI
        ):
            return Response(
                {"status": "not_configured", "detail": NOT_CONFIGURED_MESSAGE},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        serializer = OIDCExchangeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            claims = verify_id_token(serializer.validated_data["id_token"])
        except jwt.PyJWTError:
            logger.warning("OIDC exchange refused: ID-token verification failed")
            return Response(
                {"detail": INVALID_TOKEN_MESSAGE},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except (httpx.HTTPError, ValueError):
            logger.warning("OIDC exchange refused: the IdP's JWKS is unavailable")
            return Response(
                {"detail": IDP_UNAVAILABLE_MESSAGE},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        slug = claims.get(settings.OIDC_TENANT_CLAIM)
        tenant = Tenant.objects.filter(slug=str(slug).strip()).first() if slug else None
        if tenant is None:
            logger.warning("OIDC exchange refused: tenant claim resolves to no tenant")
            return Response(
                {"detail": NO_TENANT_MESSAGE},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            user = _resolve_user(claims, tenant)
            membership = self._bound_membership(user, tenant)
        except _ExchangeRefused:
            return Response(
                {"detail": NO_ACCOUNT_MESSAGE},
                status=status.HTTP_403_FORBIDDEN,
            )

        refresh = TenantAwareTokenSerializer.get_token(user)
        if api_settings.UPDATE_LAST_LOGIN:
            user.last_login = timezone.now()
            user.save(update_fields=["last_login"])
        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                MFA_CLAIM: getattr(user, "otp_device", None) is not None,
                TENANT_CLAIM: str(membership.tenant_id),
                FACILITY_CLAIM: (
                    str(membership.facility_id) if membership.facility_id else None
                ),
                ROLE_CLAIM: membership.role.name,
                PERMISSIONS_CLAIM: list(membership.role.permissions or []),
                REQUIRES_MFA_CLAIM: bool(membership.role.require_mfa),
            }
        )

    def _bound_membership(self, user, tenant):
        """The account's active membership on the bound tenant, and it must be
        the account's active membership — the pair must bind exactly the tenant
        the sign-on named, so an account whose primary membership sits on
        another tenant is refused rather than issued a token for it.
        """
        membership = (
            UserMembership.objects.select_related("role")
            .filter(user=user, tenant=tenant, active=True)
            .first()
        )
        if membership is None:
            raise _ExchangeRefused()
        primary = active_membership(user)
        if primary is None or primary.tenant_id != tenant.id:
            raise _ExchangeRefused()
        return membership
