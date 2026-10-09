"""Seed-command guards prevent production use and hard-coded credentials."""
import pytest
from django.core.management.base import CommandError
from django.test import override_settings

from apps.identity_tenancy.management.commands.seed_dev_data import Command

pytestmark = pytest.mark.unit


@override_settings(DEBUG=False)
def test_seed_command_refuses_to_run_outside_debug():
    """The development-only tenant and superuser seed must not run in production."""
    with pytest.raises(CommandError, match="only available when DEBUG=True"):
        Command().handle()


@override_settings(DEBUG=True)
def test_seed_command_requires_admin_password_from_environment(monkeypatch):
    """Seeding must never create an account with a source-controlled password."""
    monkeypatch.delenv("MEDIFLOW_SEED_ADMIN_PASSWORD", raising=False)

    with pytest.raises(CommandError, match="MEDIFLOW_SEED_ADMIN_PASSWORD"):
        Command().handle()


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_seed_platform_role_can_revoke_break_glass(monkeypatch):
    """The seeded platform admin must revoke what it can grant (TEN-007).

    The seeded ``platform_admin`` role carries ``allows_break_glass`` so a
    fresh dev database can open emergency access, but a grant is only
    reversible through ``identity.break_glass.revoke`` — a role that can open
    an emergency read and never close it is exactly the grant-without-revoke
    asymmetry TEN-007 exists to prevent. The gap cannot be repaired through
    the API because ``RoleViewSet``'s queryset excludes platform-scope roles
    (``tenant is None``), which is precisely why the seed itself must ship
    the code. Running the real command pins the role a fresh database gets,
    not a hand-edited copy of the permissions list.
    """
    from apps.identity_tenancy.models import Role

    monkeypatch.setenv("MEDIFLOW_SEED_ADMIN_PASSWORD", "pw-for-tests-only")
    Command().handle()

    platform_role = Role.objects.get(tenant=None, name="platform_admin")
    assert platform_role.allows_break_glass is True
    assert "identity.break_glass.revoke" in platform_role.permissions