"""Permission-claim enforcement for write endpoints (TEN-004).

``TenantAwareTokenSerializer`` copies ``Role.permissions`` into the access
token's ``permissions`` claim at issuance. Until this module nothing read it
back: authentication plus the MFA gate were the only server-side authorisation,
so any authenticated user could write roles, memberships and tenancy roots.
This module closes that gap.

Declaration note
----------------
DRF instantiates ``permission_classes`` entries with no arguments
(``APIView.get_permissions`` literally does ``permission()``), so a class whose
``__init__`` requires the permission code cannot be listed there directly —
``RequirePermission("some.code")`` would be re-called as an instance and raise
"object is not callable" on every request. Viewsets therefore return the
constructed instance from ``get_permissions()`` instead; ``WritePermissionMixin``
does that in one place, and ``TenantViewSet`` appends the instance itself.

Fail closed
-----------
The check reads ``request.auth.payload`` through
``common.authentication.claims_from``, which documents why the payload
attribute and not mapping access (SimpleJWT 5.x tokens are no longer dicts). A
request without a validated token, or whose claim is missing or malformed, has
no proof of the permission and is denied. Session-authenticated requests
(browsable API) consequently cannot write gated resources — they carry no
signed claims to read, which is the safe direction to fail.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from common.authentication import claims_from


class RequirePermission(BasePermission):
    """Deny a request whose ``permissions`` claim lacks the given code.

    Constructed per code (``RequirePermission("identity.roles.write")``) and
    returned from ``get_permissions`` — see the module docstring for why it
    never sits in ``permission_classes`` itself. The 403 detail names the
    missing code so an API consumer can tell this denial from the MFA gate's
    (which carries ``code = "mfa_required"``) without guessing.
    """

    def __init__(self, permission: str) -> None:
        self.permission = permission
        self.message = f"This action requires the '{permission}' permission."

    def has_permission(self, request, view) -> bool:
        claims = claims_from(request)
        permissions = claims.get("permissions")
        # An absent claim (no token, no membership, pre-TEN-004 token) reads
        # as None and fails the isinstance check: absence never grants.
        return isinstance(permissions, list) and self.permission in permissions


class WritePermissionMixin:
    """Gate unsafe methods on a permission claim; reads keep the defaults.

    Appended to whatever ``super().get_permissions()`` returns — for a viewset
    that does not declare ``permission_classes`` that is the project-wide
    deny-by-default list (``IsAuthenticated`` + ``MFARequiredIfConfigured``),
    so the MFA gate stays in force on both paths even though this viewset
    overrides ``get_permissions``.

    Reads are deliberately ungated beyond authentication: listing a resource
    is authorised by the authenticated principal plus tenant scoping
    (TEN-002); changing it requires the claim (TEN-004).
    """

    #: Permission code required for POST/PUT/PATCH/DELETE.
    write_permission: str

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.request.method not in SAFE_METHODS:
            permissions.append(RequirePermission(self.write_permission))
        return permissions
