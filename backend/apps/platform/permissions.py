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
    ABD-014 alert already filter on. It is used rather than a role *name* because
    ``Role.name`` is tenant-authored free text: "Super Admin" is one hospital's
    spelling and "Hospital Administrator" another's, so a name match would deny
    the write to most tenants and grant it where the name happened to be guessed
    right. ``Role`` has no ``is_admin`` column to consult instead.

    The membership is read from the **database**, not from the token's claims.
    Claims are a copy of the answer taken when the token was issued, so a
    membership revoked a minute ago would still grant the write until the token
    expired - and a token minted with a privileged claim by any other route would
    grant it immediately. One query on a configuration write is the cheap side of
    that trade. Three things must all hold, and each is load-bearing: the
    principal is authenticated, the request resolved a tenant, and there is an
    *active* membership in **that** tenant whose role is privileged.

    A request with no tenant resolves to no membership and is refused, which is
    the fail-closed direction: authority is authority *somewhere*, and there is
    no tenant here to say where.

    Note the interaction with TEN-006's own gate: a privileged role is required
    to present a second factor on every default-permission endpoint, so in
    practice this route is reached with an MFA-verified token or not at all. That
    is the ordering the requirements ask for, not an accident of this class.
    """

    message = (
        "Only a privileged administrator of this tenant may change a feature "
        "flag."
    )
    code = "platform_admin_required"

    def has_permission(self, request, view) -> bool:
        # ``apps.identity_tenancy.models`` is imported here rather than at module
        # scope, following the convention in ``common/tenant.py`` and
        # ``apps/workers/tasks.py``: this module is reachable from
        # ``apps.platform.views``, which is imported while the app registry is
        # still loading, and a model import at that point can raise
        # AppRegistryNotReady.
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
