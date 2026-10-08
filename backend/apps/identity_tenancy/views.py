"""Identity and administration views."""
from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from common.tenant import TENANT_REQUIRED_MESSAGE, TenantScopedQuerysetMixin
from .models import BreakGlassAccess, Department, Facility, Role, ServiceUnit, StaffPosition, Tenant, Ward, Bed, UserMembership
from .permissions import RequirePermission, WritePermissionMixin
from .serializers import (
    BreakGlassAccessSerializer, DepartmentSerializer, FacilitySerializer,
    RoleSerializer, ServiceUnitSerializer, StaffPositionSerializer,
    TenantSerializer, WardSerializer, BedSerializer, UserMembershipSerializer,
    UserCreateSerializer, UserSerializer,
)


class TenantViewSet(viewsets.ModelViewSet):
    """Tenants are the tenancy root, so they are not tenant-scoped.

    They are platform-owned instead: every method — list, detail, create and
    the onboard action — requires the ``platform.tenants.manage`` claim
    (TEN-004, TEN-010), which the platform-scope role (``Role.tenant is None``)
    is expected to hold. A tenant administrator must be able to neither
    enumerate other hospitals' tenants nor mint new ones.
    """
    serializer_class = TenantSerializer
    queryset = Tenant.objects.all()

    def get_permissions(self):
        # Appended after the defaults, so anonymous requests still fail as 401
        # (IsAuthenticated first) and the MFA gate stays in force — see
        # common/mfa.py on views replacing DEFAULT_PERMISSION_CLASSES.
        return [*super().get_permissions(), RequirePermission("platform.tenants.manage")]

    @action(detail=False, methods=["post"])
    def onboard(self, request):
        """Repeatable tenant onboarding with seed configuration (TEN-010)."""
        serializer = TenantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class FacilityViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = FacilitySerializer
    queryset = Facility.objects.all()


class DepartmentViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = DepartmentSerializer
    queryset = Department.objects.all()


class WardViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = WardSerializer
    queryset = Ward.objects.all()


class BedViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = BedSerializer
    queryset = Bed.objects.all()


class ServiceUnitViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = ServiceUnitSerializer
    queryset = ServiceUnit.objects.all()


class StaffPositionViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = StaffPositionSerializer
    queryset = StaffPosition.objects.all()


class RoleViewSet(WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Role management (TEN-004).

    Scoping keeps each hospital's role catalogue — names and permission
    bundles — out of every other tenant's list. Platform-scope roles
    (``tenant is None``) belong to no tenant's list either: exposing them
    here would let a tenant administrator edit the platform's own roles.
    Writes require the ``identity.roles.write`` claim.
    """
    serializer_class = RoleSerializer
    queryset = Role.objects.all()
    write_permission = "identity.roles.write"


class UserMembershipViewSet(WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Tenant membership assignment (TEN-004).

    Tenant stamping and the audit trail (AUD-001) both come from
    ``TenantScopedQuerysetMixin``'s ``perform_*`` hooks — the local
    ``perform_create`` this viewset used to carry duplicated the stamping and
    wrote no audit row. Writes require the ``identity.memberships.write`` claim.
    """
    serializer_class = UserMembershipSerializer
    queryset = UserMembership.objects.all()
    write_permission = "identity.memberships.write"


class UserViewSet(WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Tenant user management (TEN-008).

    ``auth.User`` has no tenant column, so scoping runs through the
    membership join (``tenant_field = "memberships__tenant_id"``): a
    cross-tenant detail lookup resolves nothing and 404s, never 403s — the
    existence of another hospital's account is itself not disclosed. Writes
    (create, patch, deactivate) require the ``identity.users.manage`` claim;
    reads are authorised by the authenticated principal plus tenant scoping,
    the same contract ``WritePermissionMixin`` states for roles. DELETE and
    PUT are not routed at all: offboarding is deactivation
    (``POST {id}/deactivate/``), because deleting the account would orphan
    every audit row pointing at it, and unbounded replaces (PUT) are not part
    of the interface.
    """
    serializer_class = UserSerializer
    queryset = get_user_model().objects.prefetch_related("memberships")
    write_permission = "identity.users.manage"
    #: No "delete" or "put": see the docstring — deactivation is the only
    #: offboarding path, so ModelViewSet's generated destroy must not route.
    http_method_names = ["get", "post", "patch", "head", "options"]
    #: auth.User has no tenant_id column; the UserMembership join is the
    #: tenant binding. unique_together(user, tenant) guarantees at most one
    #: matching row per tenant, so the join cannot duplicate list results.
    tenant_field = "memberships__tenant_id"

    def get_serializer_class(self):
        """POST create gets the write serializer; every other verb reads."""
        if self.action == "create":
            return UserCreateSerializer
        return UserSerializer

    @extend_schema(request=UserCreateSerializer, responses={201: UserSerializer})
    def create(self, request, *args, **kwargs):
        """Declared only so the schema records both shapes.

        Without it drf-spectacular documents the 201 body as
        UserCreateSerializer's fields, which omit the id and membership
        state the endpoint actually returns; behaviour is unchanged.
        """
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Stamp the tenant, create atomically, write the AUD-001 event.

        The mixin's own ``perform_create`` would call
        ``serializer.save(memberships__tenant_id=...)`` — a keyword that
        cannot write a join row — so the stamp is passed as ``tenant_id``
        for the serializer's ``create()`` to consume, and the mixin's
        tenant guard and audit call are replicated here. The transaction is
        explicit because ``ATOMIC_REQUESTS`` is False in the test profile:
        the user row and its membership must land together or not at all.
        """
        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied(TENANT_REQUIRED_MESSAGE)
        serializer.save(tenant_id=tenant_id)
        self._write_audit_log(serializer.instance, "create")

    @extend_schema(responses=UserSerializer)
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Switch this tenant's membership off instead of deleting the user (TEN-008).

        The account row survives so audit history stays resolvable, and
        ``TenantAwareTokenSerializer.validate`` refuses the next login. An
        already-deactivated membership is the same end state: 200 without a
        second audit row, so retries are harmless.
        """
        user = self.get_object()  # tenant-scoped: a foreign id 404s here
        # Read the membership through ``user.memberships`` rather than a fresh
        # query: the queryset prefetches, so a separately-fetched instance
        # would leave the prefetched row stale and the serialized response
        # would report ``active: true`` right after flipping it to false.
        membership = next(
            (
                m
                for m in user.memberships.all()
                if str(m.tenant_id) == str(self.get_tenant_id())
            ),
            None,
        )
        if membership is None:
            # Unreachable while the queryset joins on the same tenant — only
            # a concurrent delete could land here. 404 rather than a 500.
            raise NotFound("No membership for this user in the current tenant.")
        if membership.active:
            membership.active = False
            membership.save(update_fields=["active"])
            self._write_audit_log(user, "deactivate")
        return Response(self.get_serializer(user).data)


class BreakGlassViewSet(TenantScopedQuerysetMixin, viewsets.GenericViewSet):
    """Recorded break-glass access: administrative listing and revocation (TEN-007).

    The grant stays on ``auth_views.BreakGlassView`` (``POST /auth/break-glass/``),
    which enforces the role claim, the mandatory reason header and the AUD-001
    and alert writes. This viewset is the administrative half: the
    tenant-scoped record list an audit screen (Task 34) reads, and the revoke
    action that ends a grant.

    Every method demands the ``identity.break_glass.revoke`` claim, appended
    after the defaults the same way ``TenantViewSet`` appends one platform
    claim over every method — listing grants is as sensitive as revoking one,
    so a single gate covers both rather than leaving the list behind.
    """

    serializer_class = BreakGlassAccessSerializer
    queryset = BreakGlassAccess.objects.all()

    # No ``permission_classes`` attribute: declaring one would replace the
    # project defaults (IsAuthenticated + MFARequiredIfConfigured) wholesale —
    # see base.py on views that declare their own. Inheriting them keeps the
    # TEN-006 MFA gate in force over list and revoke exactly as TenantViewSet
    # does, and ``get_permissions`` below appends the claim check after them.
    def get_permissions(self):
        return [*super().get_permissions(), RequirePermission("identity.break_glass.revoke")]

    @extend_schema(responses=BreakGlassAccessSerializer(many=True))
    def list(self, request):
        return Response(
            BreakGlassAccessSerializer(self.get_queryset(), many=True).data
        )

    @extend_schema(
        responses=BreakGlassAccessSerializer,
        description=(
            "Revoke a break-glass grant (TEN-007). GET is what the interface "
            "specifies; the action is idempotent — a retried revoke restamps "
            "revoked_at and answers 200 again."
        ),
    )
    @action(detail=True, methods=["get"])
    def revoke(self, request, pk=None):
        """Stamp ``revoked_at`` so the grant no longer passes its check (TEN-007).

        ``self.get_object()`` resolves through the tenant-scoped queryset, so
        a foreign or unknown id answers 404 before any write — the existence
        of another hospital's grant is not disclosed, and this request can
        never touch it. An already-revoked grant is the same end state:
        re-stamping is harmless, so retries are idempotent.
        """
        access = self.get_object()
        access.revoked_at = timezone.now()
        access.save(update_fields=["revoked_at"])
        return Response(BreakGlassAccessSerializer(access).data)
