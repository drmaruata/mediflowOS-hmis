"""Transactional tenant onboarding with seed configuration (TEN-010, TEN-011)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from .models import Department, Facility, Role, Tenant, UserMembership
from .serializers import OnboardAdminSerializer

#: Permission bundles seeded onto the roles every onboarding mints. Explicit
#: codes only — "all" is a human marker the RBAC gate never reads (see
#: seed_dev_data.py) — and no "platform.*" code: RoleSerializer refuses those
#: on tenant-scoped roles (TEN-004), and both seeds below are tenant-scoped.
PLATFORM_ADMIN_SEED_PERMISSIONS = [
    "identity.users.manage",
    "identity.roles.write",
    "identity.memberships.write",
    "identity.break_glass.revoke",
]

TENANT_ADMIN_SEED_PERMISSIONS = [
    "identity.users.manage",
    "identity.roles.write",
    "identity.memberships.write",
]


def onboard_tenant(
    *,
    name: str,
    slug: str,
    facility: dict,
    admin: dict,
    abdm: dict | None = None,
) -> Tenant:
    """Create a whole hospital in one transaction (TEN-010, TEN-011).

    One ``transaction.atomic()`` block mints the tenant, its first facility
    (carrying the ABDM identifiers when ``abdm`` is given — TEN-011), the
    default OPD/IPD departments, the seeded ``platform_admin`` and
    ``tenant_admin`` roles, and the first admin user with its active
    membership.

    The admin is validated *after* the tenant row is written, inside the same
    block: a bad payload must take every seeded row with it, so a partially
    boarded hospital can never exist. ATOMIC_REQUESTS is False in the test
    profile, so the transaction lives here rather than being trusted to the
    view layer.
    """
    with transaction.atomic():
        tenant = Tenant.objects.create(name=name, slug=slug)
        facility_row = Facility.objects.create(
            tenant=tenant,
            name=facility["name"],
            level=facility["level"],
            # TEN-011: identifiers are stored at onboarding when the client
            # has NHA data to hand; without it the model's default
            # registration status ("pending") documents the outstanding step.
            abdm_hip_id=(abdm or {}).get("abdm_hip_id"),
            abdm_facility_id=(abdm or {}).get("abdm_facility_id"),
            abdm_registration_status=(abdm or {}).get(
                "abdm_registration_status", "pending"
            ),
        )
        _seed_departments(tenant, facility_row)
        platform_admin_role = _seed_roles(tenant)
        _create_admin(admin, tenant, platform_admin_role)
        return tenant


def _seed_departments(tenant: Tenant, facility: Facility) -> None:
    """Seed the default OPD and IPD departments (TEN-010).

    They start with opposite service switches so the two queues never both
    accept the first token: OPD takes outpatients, IPD takes inpatients. A
    hospital without either department would warn every downstream queue the
    moment a patient arrives, so both are created unconditionally.
    """
    today = date.today()
    Department.objects.create(
        tenant=tenant,
        facility=facility,
        name="OPD",
        opd_enabled=True,
        ipd_enabled=False,
        active=True,
        effective_from=today,
    )
    Department.objects.create(
        tenant=tenant,
        facility=facility,
        name="IPD",
        opd_enabled=False,
        ipd_enabled=True,
        active=True,
        effective_from=today,
    )


def _seed_roles(tenant: Tenant) -> Role:
    """Seed the roles a new tenant needs before any account exists (TEN-010).

    Returns the ``platform_admin`` role, which is the one the first account
    is bound to; ``tenant_admin`` is created for the hospital's own admins to
    be assigned later.
    """
    platform_admin_role = Role.objects.create(
        tenant=tenant,
        name="platform_admin",
        permissions=PLATFORM_ADMIN_SEED_PERMISSIONS,
    )
    Role.objects.create(
        tenant=tenant,
        name="tenant_admin",
        permissions=TENANT_ADMIN_SEED_PERMISSIONS,
    )
    return platform_admin_role


def _create_admin(admin: dict, tenant: Tenant, role: Role) -> None:
    """Create the first account and bind it with an active membership.

    The payload is validated through :class:`OnboardAdminSerializer` — whose
    password rule is delegated from Task 3's ``UserCreateSerializer`` — so the
    direct-call contract and the API contract reject the same payloads. The
    validation raises *inside* the caller's atomic block, which is what rolls
    the whole boarding back when the admin is unusable.
    """
    serializer = OnboardAdminSerializer(data=admin)
    serializer.is_valid(raise_exception=True)
    username = serializer.validated_data["username"]
    if get_user_model().objects.filter(username=username).exists():
        # Usernames are installation-global. The slug was written first, so
        # by the time we reach here the conflict is genuinely the account,
        # not the tenancy — nest under "admin" to match the password error's
        # shape, and let the caller's atomic block roll the boarding back.
        raise serializers.ValidationError(
            {"admin": {"username": ["A user with that username already exists."]}}
        )
    user = get_user_model().objects.create_user(**serializer.validated_data)
    UserMembership.objects.create(
        user=user,
        tenant=tenant,
        role=role,
        active=True,
    )