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