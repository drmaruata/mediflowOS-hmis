"""Configuration-level assertions.

These guard settings and wiring that no single behavioural test would otherwise
notice, because they only matter in combination across modules.
"""
from unittest import mock

import pytest
from django.conf import settings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("module", ["base", "dev"])
def test_requests_are_transactional(module):
    """Tenant context is transaction-scoped, so a request needs a transaction.

    ``TenantMiddleware`` sets ``app.tenant_id`` with
    ``set_config(..., is_local=true)``. PostgreSQL discards that value when the
    enclosing transaction ends. Without ``ATOMIC_REQUESTS`` the setting would
    be dropped by the implicit autocommit transaction before any tenant-owned
    query ran, leaving queries with no tenant context at all.
    """
    import importlib

    settings_module = importlib.import_module(f"config.settings.{module}")
    database = settings_module.DATABASES["default"]

    assert database.get("ATOMIC_REQUESTS") is True, (
        f"config.settings.{module} must set ATOMIC_REQUESTS so the tenant "
        "session setting survives for the whole request"
    )


def test_deny_by_default_permissions():
    """The data plane must not fall back to DRF's implicit AllowAny."""
    permissions = settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]

    assert permissions == ["rest_framework.permissions.IsAuthenticated"]


def test_authentication_is_configured():
    """At least one real authentication class must be registered."""
    classes = settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]

    assert classes, "DEFAULT_AUTHENTICATION_CLASSES must not be empty"
    assert any("JWTAuthentication" in entry for entry in classes), (
        "JWT authentication is expected; the architecture doc specifies "
        "Keycloak-issued bearer tokens carrying tenant_id, facility_id, roles"
    )


def test_tenant_middleware_is_installed():
    assert "common.tenant.TenantMiddleware" in settings.MIDDLEWARE


def test_session_authentication_alongside_jwt():
    """Session auth supports the browsable API and admin; it must not be the
    only backend, or the browsable API would be the sole auth path."""
    classes = settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]

    assert "rest_framework.authentication.SessionAuthentication" in classes
    assert len(classes) > 1


def test_abdm_callback_has_its_own_throttle_budget():
    """The anonymous gateway path must not share the global anon budget."""
    assert "abdm_callback" in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]


def test_postgres_engine_resolves_dotted_db_tables():
    """The custom backend must be importable as Django requires.

    Django imports a custom ENGINE as ``<ENGINE>.base``, so ``common.postgres``
    must be a package exposing ``base.DatabaseWrapper``. A regression here
    breaks every management command with a confusing
    "is not a package" error.
    """
    from django.utils.module_loading import import_string

    wrapper = import_string("common.postgres.base.DatabaseWrapper")

    assert hasattr(wrapper, "SchemaEditorClass")
    assert wrapper.SchemaEditorClass.__name__ == "SchemaQualifiedSchemaEditor"


def _postgres_operations():
    """The operations class from the custom backend, without connecting.

    The test settings run on SQLite, so the project's live connection does not
    exercise the PostgreSQL quoting rules. This instantiates the operations
    directly; no server is needed because quoting is pure string handling.
    """
    from common.postgres.base import DatabaseOperations

    connection = mock.Mock()
    connection.ops = DatabaseOperations(connection)
    connection.features = mock.Mock(supports_schema_names=True)
    return connection.ops


def test_schema_editor_only_splits_exact_table_names():
    """Index and constraint names also contain dots and must stay whole.

    Django derives index and foreign key constraint names from ``db_table``, so
    an index on ``registry.patient`` is called
    ``registry.patient_tenant_id_uhid_9f3a1c_idx``. Schema-qualifying that
    would truncate it and, for a cross-module foreign key, would produce
    ``ALTER TABLE ... ADD CONSTRAINT "schema"."name"``, which PostgreSQL
    rejects.
    """
    from apps.identity_tenancy.models import Tenant
    from django.apps import apps

    from common.postgres.quoting import qualified_table_names

    quote = _postgres_operations().quote_name

    assert quote("registry.patient") == '"registry"."patient"'
    # An index name that merely starts with a table name is not split.
    assert quote("registry.patient_tenant_id_9f3a1c_idx") == (
        '"registry.patient_tenant_id_9f3a1c_idx"'
    )
    # A foreign key constraint name spanning two modules stays one identifier.
    assert quote("registry.qr_code_facility_id_81301309_fk_identity.facility_id") == (
        '"registry.qr_code_facility_id_81301309_fk_identity.facility_id"'
    )
    # Django's own tables live in public and must be left alone.
    assert quote("auth_user") == '"auth_user"'
    assert quote("tenant_id") == '"tenant_id"'
    assert Tenant._meta.db_table in qualified_table_names()
    assert apps.get_models()


def test_runtime_queries_resolve_schema_qualified_tables():
    """Quoting must apply to ORM queries, not only to DDL.

    Django compiles a table reference from ``db_table`` at query time, so
    schema awareness has to live on the connection operations. If it only lived
    on the schema editor, every SELECT would ask for a relation literally named
    ``identity.tenant`` and fail with "relation does not exist".
    """
    from apps.patient_registry.models import Patient

    ops = _postgres_operations()
    assert ops.quote_name(Patient._meta.db_table) == '"registry"."patient"'