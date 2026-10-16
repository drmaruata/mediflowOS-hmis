"""Authorisation for platform configuration writes (PLT-006).

Reading a tenant's configuration is authenticated-and-tenant-scoped, like any
other read (TEN-002). Changing it is not: a feature flag is a decision about what
a whole hospital gets to use, and the audience for that decision is a small one.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from common.tenant import REQUEST_TENANT_ATTR


class IsPrivilegedTenantMember(BasePermission):
    """Allow only a member of the request's tenant holding a privileged role.

    The predicate is ``Role.require_mfa`` (TEN-006) - the documented
    privileged-role marker, and the one the TEN-007 break-glass fan-out and the
    ABD-014 alert already filter on. Not a role *name*, because ``Role.name`` is
    tenant-authored free text: "Super Admin" is one hospital's spelling and
    "Hospital Administrator" another's, so a name match would deny the write to
    most tenants and grant it where the name happened to be guessed right.

    The membership is read from the **database**, not the token's claims: claims
    are a copy taken at issuance, so a membership revoked a minute ago would still
    grant the write until the token expired, and a token minted with a privileged
    claim by any other route would grant it immediately. Three things must all
    hold, and each is load-bearing: the principal is authenticated, the request
    resolved a tenant, and there is an *active* membership in **that** tenant
    whose role is privileged. A request with no tenant resolves to no membership
    and is refused - the fail-closed direction.

    Interaction with TEN-006's own gate: a privileged role must present a second
    factor on every default-permission endpoint, so in practice this route is
    reached with an MFA-verified token or not at all. That ordering is what the
    requirements ask for, not an accident of this class.
    """

    message = (
        "Only a privileged administrator of this tenant may change a feature "
        "flag."
    )
    code = "platform_admin_required"

    def has_permission(self, request, view) -> bool:
        # Imported here, not at module scope: this module is reachable from
        # ``apps.platform.views``, which is imported while the app registry is
        # still loading, and a model import then raises AppRegistryNotReady.
        from apps.identity_tenancy.models import UserMembership

        user = getattr(request, "user", None)
        tenant_id = getattr(request, REQUEST_TENANT_ATTR, None)
        if user is None or not user.is_authenticated or not tenant_id:
            return False
        return UserMembership.objects.filter(
            user=user,
            tenant_id=tenant_id,
            active=True,
            role__require_mfa=True,
        ).exists()


class PrivilegedWriteMixin:
    """Gate unsafe methods on a privileged membership; reads keep the defaults.

    Appended to whatever ``super().get_permissions()`` returns, so for a viewset
    that declares no ``permission_classes`` that is the project-wide
    deny-by-default list (``IsAuthenticated`` then ``MFARequiredIfConfigured``) and
    both stay in force - an anonymous caller still answers 401 rather than being
    told it is not an administrator.
    """

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.request.method not in SAFE_METHODS:
            permissions.append(IsPrivilegedTenantMember())
        return permissions
