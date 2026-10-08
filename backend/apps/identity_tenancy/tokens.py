"""JWT issuance carrying tenant context (TEN-001 to TEN-007).

Architecture doc section 7 describes the request flow as "JWT from Keycloak
carries tenant_id, facility_id, roles". This module issues that token locally so
the platform is runnable end to end, and is the single place the tenant context
on a request originates.

Why the tenant lives in the token rather than a header
------------------------------------------------------
TenantMiddleware originally took the tenant from ``X-Tenant-Id``, a
client-supplied header. Any authenticated user could therefore read another
hospital's data by changing one header, and both the ORM filter and the row level
security policy were fed from it. Binding the tenant into a signed credential
means a caller cannot assert a tenant they were not issued.

Two sources of tenant context are accepted, in priority order:

1. the authenticated principal's claims, when present;
2. the ``X-Tenant-Id`` header, which remains supported for the ABDM gateway
   callback path and for internal service-to-service calls that are
   authenticated by network position rather than by user.

A mismatch is not silently resolved in the caller's favour: if a header claims a
different tenant than the token, the token wins and the header is ignored.
"""
from django.contrib.auth import get_user_model
from django.db.models import F, Prefetch
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

TENANT_CLAIM = "tenant_id"
FACILITY_CLAIM = "facility_id"
ROLE_CLAIM = "role"
PERMISSIONS_CLAIM = "permissions"
REQUIRES_MFA_CLAIM = "requires_mfa"
MFA_CLAIM = "mfa_verified"
BREAK_GLASS_CLAIM = "allows_break_glass"


def active_membership(user):
    """The user's active membership, preferring a platform-wide role.

    A user holding a platform role (tenant null) can act for any tenant, so that
    membership is chosen first - otherwise the platform administrator who
    onboards tenants (TEN-010) could not reach a tenant they are not a member of.
    """
    memberships = user.memberships.select_related("role", "tenant").filter(active=True)
    # nulls_first puts the platform-wide role (tenant is null) ahead of any
    # hospital-scoped membership. A plain "tenant__isnull" ordering is not
    # supported; the null ordering has to be expressed on the FK value.
    return memberships.order_by(F("role__tenant_id").desc(nulls_first=True), "role__name").first()


class TenantAwareTokenSerializer(TokenObtainPairSerializer):
    """Adds the tenant, facility, role, permissions and MFA claims to the token."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # TEN-006: both MFA claims are written before the membership branch,
        # because MFARequiredIfConfigured reads them from every authenticated
        # token — including one from a membership-less account. mfa_verified
        # mirrors django-otp state: the library attaches the verified device
        # as user.otp_device, and a password-only login has none, so it reads
        # False. Fail closed — a token that has not proven a second factor
        # never claims it has.
        token[MFA_CLAIM] = getattr(user, "otp_device", None) is not None

        membership = active_membership(user)
        if membership is None:
            # No membership means no tenant. The token is still issued, but the
            # tenant claims stay null and every tenant-scoped queryset resolves
            # to empty. Denying the login outright would be clearer, but the
            # account may legitimately be mid-onboarding; isolation fails
            # closed either way.
            token[TENANT_CLAIM] = None
            token[FACILITY_CLAIM] = None
            token[ROLE_CLAIM] = None
            token[PERMISSIONS_CLAIM] = []
            token[BREAK_GLASS_CLAIM] = False
            token[REQUIRES_MFA_CLAIM] = False
            return token

        token[TENANT_CLAIM] = str(membership.tenant_id)
        token[FACILITY_CLAIM] = str(membership.facility_id) if membership.facility_id else None
        token[ROLE_CLAIM] = membership.role.name
        token[PERMISSIONS_CLAIM] = list(membership.role.permissions or [])
        token[BREAK_GLASS_CLAIM] = bool(membership.role.allows_break_glass)
        token[REQUIRES_MFA_CLAIM] = bool(membership.role.require_mfa)
        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        user = self.user
        membership = active_membership(user)

        # TEN-008: deactivation flips UserMembership.active, and this is the
        # point where that must bite. active_membership() above already
        # ignores inactive rows, so without this check a deactivated account
        # would still be issued the null-claim token below - logged in, just
        # unscoped. A user with NO membership keeps the existing fail-closed
        # semantics (the account may be mid-onboarding; see get_token): only
        # a membership that exists and has been switched off refuses the
        # login. Running after super().validate means the password has
        # already been verified, so this cannot be used to probe which
        # accounts are deactivated.
        if membership is None and user.memberships.exists():
            raise AuthenticationFailed("This account's membership has been deactivated.")

        # The claim is an enforcement input, not just display data: the
        # MFARequiredIfConfigured default permission reads requires_mfa and
        # this mfa_verified claim to gate default-permission endpoints.
        # django-otp's state (user.otp_device) is what feeds the claim at
        # issuance; publishing it in the response body too lets the frontend
        # prompt for a second factor without a second round trip.
        device = getattr(user, "otp_device", None)
        data[MFA_CLAIM] = device is not None

        if membership is not None:
            data["tenant_id"] = str(membership.tenant_id)
            data["facility_id"] = (
                str(membership.facility_id) if membership.facility_id else None
            )
            data["role"] = membership.role.name
            data["permissions"] = list(membership.role.permissions or [])
            data["requires_mfa"] = bool(membership.role.require_mfa)
        else:
            data["tenant_id"] = None
            data["facility_id"] = None
            data["role"] = None
            data["permissions"] = []
            data["requires_mfa"] = False

        return data


def user_with_memberships(user):
    """Eager-load memberships so the token view does not fan out queries."""
    return get_user_model().objects.filter(pk=user.pk).prefetch_related(
        Prefetch(
            "memberships",
            queryset=active_membership_queryset(),
            to_attr="_active_memberships",
        )
    ).first()


def active_membership_queryset():
    from apps.identity_tenancy.models import UserMembership

    return UserMembership.objects.select_related("role", "tenant").filter(active=True)