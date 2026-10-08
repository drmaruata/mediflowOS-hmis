"""Serializers for identity and tenancy."""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from .models import (
    BreakGlassAccess, Department, Facility, Role, ServiceUnit, StaffPosition,
    Tenant, Ward, Bed, UserMembership,
)


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "tier", "accreditation_profile", "db_mode", "created_at"]
        read_only_fields = ["id", "created_at"]


class FacilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Facility
        fields = "__all__"
        read_only_fields = ["id", "created_at"]


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = "__all__"
        read_only_fields = ["id"]


class WardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ward
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class BedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bed
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class ServiceUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceUnit
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class StaffPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffPosition
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = "__all__"
        # tenant is server-owned: TenantScopedQuerysetMixin stamps it on
        # create, and a writable tenant on update would let a caller move a
        # role into another tenant (common/tenant.py states this contract).
        read_only_fields = ["id", "created_at", "tenant"]

    def validate_permissions(self, value):
        """Refuse platform-scope codes on tenant-scoped roles (TEN-004).

        Platform scope is defined as ``Role.tenant is None``, but until now
        nothing enforced it: a tenant admin holding ``identity.roles.write``
        could PATCH ``platform.tenants.manage`` onto their own role, re-login,
        and pass the ``TenantViewSet`` gate that enumerates and mints
        hospitals. This is the write-path half of that constraint —
        token-level scope binding (checking the role's scope at claim
        issuance) is deliberately deferred.

        Updates consult the stored role's tenant. Creates are refused
        outright rather than consulted: ``RoleViewSet`` is tenant-scoped and
        stamps the request's tenant in ``perform_create``, so a role created
        through the API is always tenant-owned — a platform-scoped create
        would need a platform-level viewset, which does not exist.

        Only codes literally starting with ``platform.`` are rejected, which
        is exactly the set ``RequirePermission`` can ever match (exact list
        membership), so a padded or non-string entry grants nothing.

        List elements and dict keys are both checked because ``tokens.py``
        builds the claim with ``list(role.permissions or [])`` — ``list()`` on
        a dict yields its *keys*, so a dict key carrying a platform code would
        grant it just as a list element would. Any other JSON shape passes
        through untouched: a non-list claim can never satisfy
        ``RequirePermission``, so nothing in it can grant.
        """
        if isinstance(value, list):
            candidates = value
        elif isinstance(value, dict):
            candidates = list(value.keys())
        else:
            # See the docstring: a string iterates to single characters when
            # the claim is built, so no non-list shape can ever satisfy
            # RequirePermission — pass it through instead of raising here.
            return value
        platform_codes = [
            code
            for code in candidates
            if isinstance(code, str) and code.startswith("platform.")
        ]
        if not platform_codes:
            return value
        # A create (self.instance is None) is always tenant-owned — see above.
        if self.instance is None or self.instance.tenant is not None:
            raise serializers.ValidationError(
                f"Platform-scope permissions {platform_codes} are reserved for "
                "platform-scoped roles (Role.tenant is None)."
            )
        return value


class UserMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserMembership
        fields = "__all__"
        read_only_fields = ["id", "active", "tenant"]


class BreakGlassAccessSerializer(serializers.ModelSerializer):
    class Meta:
        model = BreakGlassAccess
        fields = "__all__"
        read_only_fields = ["id", "granted_at", "tenant_id"]


class UserSerializer(serializers.ModelSerializer):
    """Read shape of a tenant-managed user (TEN-008).

    ``auth.User`` carries no tenant column, so membership state is read from
    the membership joining this user to the *request's* tenant — the same
    join ``UserViewSet`` scopes its queryset with, which is why the fields
    below are membership-scoped rather than global. The password hash is
    absent by construction: ``password`` is not among ``fields``, so neither
    a read nor a create response can serialise it.

    Only ``username`` and ``email`` are writable (PATCH); ``is_active`` is
    deliberately not exposed, because deactivation is membership state
    (``UserMembership.active``), not the Django account flag — two
    overlapping deactivation paths would disagree the moment one was used.
    """
    role_id = serializers.SerializerMethodField()
    facility_id = serializers.SerializerMethodField()
    active = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = [
            "id", "username", "email", "date_joined",
            "role_id", "facility_id", "active",
        ]
        # role_id/facility_id/active are method fields and therefore already
        # read-only; they are listed so the writable surface of PATCH reads
        # as exactly [username, email] without having to know that.
        read_only_fields = ["id", "date_joined", "role_id", "facility_id", "active"]

    def _membership(self, obj):
        """This user's membership in the request's tenant, if any.

        Iterates ``obj.memberships.all()`` instead of filtering, so the
        viewset's ``prefetch_related("memberships")`` is honoured on list
        reads — a per-row ``.filter()`` would fan out one query per user.
        """
        request = self.context.get("request")
        tenant_id = getattr(request, "tenant_id", None) if request else None
        if not tenant_id:
            return None
        return next(
            (m for m in obj.memberships.all() if str(m.tenant_id) == str(tenant_id)),
            None,
        )

    def get_role_id(self, obj) -> str | None:
        membership = self._membership(obj)
        return str(membership.role_id) if membership else None

    def get_facility_id(self, obj) -> str | None:
        membership = self._membership(obj)
        if membership is None or membership.facility_id is None:
            return None
        return str(membership.facility_id)

    def get_active(self, obj) -> bool | None:
        membership = self._membership(obj)
        return membership.active if membership else None


class UserCreateSerializer(serializers.ModelSerializer):
    """Create payload for user management (TEN-008).

    Produces an ``auth.User`` and its active ``UserMembership`` in one
    transaction — see :meth:`create`. ``password`` is write-only and is
    hashed by ``create_user``; the repository rule that a password hash is
    never exposed holds by construction, since the only representation this
    serializer ever yields is :class:`UserSerializer`'s (see
    :meth:`to_representation`).
    """
    password = serializers.CharField(write_only=True)
    #: A bare UUID resolved through ONE tenant-scoped lookup in
    #: validate_role_id — the field itself must not fetch, or an unknown pk
    #: would fail with PrimaryKeyRelatedField's global "does not exist" while
    #: a foreign tenant's role failed with the scoped message, disclosing
    #: which pks exist anywhere. Same shape as validate_facility_id below.
    role_id = serializers.UUIDField()
    #: A bare UUID on the model (no FK), so tenant-checking happens here.
    facility_id = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = get_user_model()
        fields = ["username", "password", "email", "role_id", "facility_id"]

    def _request_tenant_id(self):
        request = self.context.get("request")
        return getattr(request, "tenant_id", None) if request else None

    def _require_tenant(self):
        """The caller's resolved tenant, or a refusal when there is none.

        Serializer validation runs *before* the viewset's
        ``perform_create``, so without this guard a tenant-less request would
        be answered with a misleading 400 ("role does not exist in this
        tenant") instead of the mixin's canonical 403.
        """
        tenant_id = self._request_tenant_id()
        if tenant_id is None:
            raise PermissionDenied(
                "A tenant must be resolved before tenant-owned data can be written."
            )
        return tenant_id

    def validate_password(self, value):
        """Minimal password policy: at least 12 characters (TEN-008).

        Length only — no composition rules — but enforced server-side,
        because client-side validation is advisory.
        """
        if len(value) < 12:
            raise serializers.ValidationError(
                "Password must be at least 12 characters long."
            )
        return value

    def validate_role_id(self, value):
        """The role must belong to the caller's tenant (TEN-008, TEN-002).

        Existence alone is not enough: the access token copies
        ``role.permissions`` verbatim, so a membership wired to another
        hospital's role — or to a platform-scoped role with ``tenant is
        None`` — would grant that role's permission bundle inside this
        tenant. The scoped lookup IS the authorisation decision, and running
        it as one filter (as ``validate_facility_id`` does below) answers
        "unknown pk" and "foreign pk" with the same refusal — a distinct
        "does not exist" error would confirm that a role pk exists somewhere
        in the installation, which is the disclosure ``validate_facility_id``
        documents avoiding. Returns the resolved instance for ``create()``.
        """
        tenant_id = self._require_tenant()
        role = Role.objects.filter(pk=value, tenant_id=tenant_id).first()
        if role is None:
            raise serializers.ValidationError("Role does not exist in this tenant.")
        return role

    def validate_facility_id(self, value):
        """The facility must belong to the caller's tenant (TEN-008, TEN-002).

        ``UserMembership.facility_id`` is an unconstrained UUID, so this is
        the only place a pointer into another hospital's facility tree is
        refused. One scoped filter answers both "unknown" and "foreign" the
        same way, so neither response confirms the other's existence.
        """
        if value is None:
            return value
        tenant_id = self._require_tenant()
        if not Facility.objects.filter(pk=value, tenant_id=tenant_id).exists():
            raise serializers.ValidationError("Facility does not exist in this tenant.")
        return value

    def create(self, validated_data):
        """Create the user and its active membership in ONE transaction (TEN-008).

        The atomicity is explicit rather than inherited from
        ``ATOMIC_REQUESTS``: that setting is False in the test profile, and
        a non-atomic caller would otherwise risk a user row without its
        membership — an account no token can ever scope. Any failure rolls
        both rows back together.

        ``tenant_id`` arrives as a ``serializer.save()`` kwarg from
        ``UserViewSet.perform_create``, mirroring how
        ``TenantScopedQuerysetMixin`` stamps other tenant-owned models.
        """
        tenant_id = validated_data.pop("tenant_id", None)
        if not tenant_id:
            # perform_create always supplies it; refusing here means a save()
            # from any other path cannot mint an unscoped membership.
            raise PermissionDenied(
                "A tenant must be resolved before tenant-owned data can be written."
            )
        role = validated_data.pop("role_id")
        facility_id = validated_data.pop("facility_id", None)
        password = validated_data.pop("password")
        with transaction.atomic():
            user = get_user_model().objects.create_user(
                password=password, **validated_data
            )
            UserMembership.objects.create(
                user=user,
                tenant_id=tenant_id,
                role=role,
                facility_id=facility_id,
                active=True,
            )
        return user

    def to_representation(self, instance):
        """The canonical read shape, so create responses match GET responses.

        Delegating to :class:`UserSerializer` keeps exactly one
        representation of a user regardless of the verb that produced it;
        this serializer is write-only plumbing.
        """
        return UserSerializer(instance, context=self.context).data
