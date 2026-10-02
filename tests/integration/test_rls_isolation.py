"""Cross-tenant isolation, verified on every tenant-owned table.

Architecture doc section 7 states the safeguard directly: "Automated tests
attempt cross-tenant reads on every table; CI fails if any succeed." This module
is that gate.

Two things make it meaningful rather than decorative:

* It connects as a role with **NOBYPASSRLS and NOSUPERUSER**. Verified while
  building this: running the same queries as the ``postgres`` superuser returns
  every tenant's rows, because superusers bypass RLS unconditionally. Testing as
  the owner would prove nothing.

* It walks the model registry, so a newly added tenant-owned table is covered
  without anyone remembering to list it. A table missing a policy fails here.

Requires a PostgreSQL database with migrations applied::

    MEDIFLOW_TEST_PGHOST=... MEDIFLOW_TEST_PGPORT=... \\
    MEDIFLOW_TEST_PGDATABASE=mediflow MEDIFLOW_TEST_PGUSER=postgres \\
    MEDIFLOW_TEST_PGPASSWORD=... pytest tests/integration/test_rls_isolation.py

Seeding runs as the migration role, which is permitted to bypass RLS; that
mirrors production, where migrations run privileged and the application does not.
"""
import os
import uuid

import pytest

from common.rls import POLICY_NAME

PGHOST = os.getenv("MEDIFLOW_TEST_PGHOST")
PGDATABASE = os.getenv("MEDIFLOW_TEST_PGDATABASE", "mediflow")
PGUSER = os.getenv("MEDIFLOW_TEST_PGUSER", "postgres")
PGPASSWORD = os.getenv("MEDIFLOW_TEST_PGPASSWORD", "postgres")
PGPORT = os.getenv("MEDIFLOW_TEST_PGPORT", "5432")

APP_ROLE = os.getenv("MEDIFLOW_TEST_PGAPPROLE", "mediflow_app")

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not PGHOST,
        reason="set MEDIFLOW_TEST_PGHOST (and MEDIFLOW_TEST_PG* variables) to "
        "run the row level security isolation gate",
    ),
]


def _tenant_owned_tables():
    """Every tenant-owned table, from the model registry.

    Discovered rather than listed so that adding a model with ``tenant_id``
    automatically brings it under test.

    Selection is by *column presence*, not by app label. A label allow-list
    goes stale the moment another installed app contributes tables - it missed
    django-otp's device table when the TOTP plugin was added, and that table has
    no tenant to isolate. Filtering on the column is both simpler and correct:
    a table without ``tenant_id`` cannot be tenant-scoped.
    """
    import os

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
    django.setup()

    from django.apps import apps as registry

    tables = []
    for config in registry.get_app_configs():
        for model in config.get_models():
            columns = {field.column for field in model._meta.concrete_fields}
            if "tenant_id" in columns:
                tables.append(model._meta.db_table)
    return sorted(set(tables))


TENANT_OWNED_TABLES = _tenant_owned_tables()


@pytest.fixture(scope="module")
def admin_connection():
    """Privileged connection, used to seed and to inspect catalog state."""
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(
        host=PGHOST, port=PGPORT, dbname=PGDATABASE, user=PGUSER, password=PGPASSWORD
    )
    connection.autocommit = True
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(scope="module")
def app_connection():
    """Connection as a role subject to RLS, mirroring the application.

    ``SET ROLE`` is used rather than a second connection so the test needs no
    second password; the role's privileges are what RLS keys off.
    """
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(
        host=PGHOST, port=PGPORT, dbname=PGDATABASE, user=PGUSER, password=PGPASSWORD
    )
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)
        )
        if cursor.fetchone() is None:
            cursor.execute(
                psycopg.sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS").format(
                    psycopg.sql.Identifier(APP_ROLE)
                )
            )
        role = psycopg.sql.Identifier(APP_ROLE)

        # Grant on every schema the application touches, mirroring the role
        # provisioning the deployment is expected to perform. Privileges are
        # granted to the role but never to BYPASSRLS - the grants are exactly
        # what makes the policy the only thing standing between tenants.
        cursor.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname NOT IN "
            "('public', 'pg_catalog', 'information_schema')"
        )
        for (schema,) in cursor.fetchall():
            cursor.execute(
                psycopg.sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
                    psycopg.sql.Identifier(schema), role
                )
            )
        cursor.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname NOT IN "
            "('pg_catalog', 'information_schema')"
        )
        for (schema,) in cursor.fetchall():
            cursor.execute(
                psycopg.sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                    "IN SCHEMA {} TO {}"
                ).format(psycopg.sql.Identifier(schema), role)
            )
        cursor.execute(psycopg.sql.SQL("SET ROLE {}").format(role))
    try:
        yield connection
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        connection.close()


def _set_tenant(connection, tenant_id) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))


#: Values for a column type, used only to satisfy NOT NULL constraints on a
#: throwaway probe row. Nothing here is meaningful clinical data.
#:
#: A value of None means "bind a parameter"; the sentinel below marks which.
#: Strings are literal SQL.
_PROBE_LITERALS = {
    "uuid": None,  # parameterised: a fresh uuid
    "character varying": None,  # parameterised: a unique token
    "text": None,
    "date": "DATE '2026-01-01'",
    "timestamp with time zone": "TIMESTAMPTZ '2026-01-01 00:00:00+00'",
    "boolean": "false",
    "integer": "1",
    "smallint": "1",
    "bigint": "1",
    "numeric": "1",
    "double precision": "1",
    "real": "1",
    "jsonb": "'{}'::jsonb",
    "json": "'{}'::json",
}


def _required_columns(connection, table: str) -> list:
    """NOT NULL columns with no database default, excluding id and tenant_id.

    Returns (name, data_type, max_length); max_length is None when unbounded.
    """
    schema, _, name = table.partition(".")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, data_type, character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "AND is_nullable = 'NO' AND column_default IS NULL "
            "AND column_name <> 'id' AND column_name <> 'tenant_id'",
            (schema, name),
        )
        return cursor.fetchall()


#: Columns that are genuine foreign keys, mapped to the table they must point
#: at. Everything else in this schema uses plain UUID columns with no
#: constraint, so a random value satisfies them.
#:
#: Only identity_tenancy and patient_registry declare ForeignKey columns. They
#: are seeded as a real spine (tenant -> facility -> department -> ward ->
#: intake_point) so the constraints hold; the probe row for every other table
#: uses generated ids.
_FK_PARENTS = {
    "identity.facility": {"tenant_id": "identity.tenant"},
    "identity.department": {"tenant_id": "identity.tenant", "facility_id": "identity.facility"},
    "identity.ward": {"department_id": "identity.department"},
    "identity.bed": {"ward_id": "identity.ward"},
    "identity.service_unit": {"facility_id": "identity.facility"},
    "identity.staff_position": {"department_id": "identity.department"},
    "registry.intake_point": {"facility_id": "identity.facility"},
    "registry.qr_code": {"facility_id": "identity.facility", "intake_point_id": "registry.intake_point"},
    "quality.framework_edition": {"framework_id": "quality.framework"},
    "quality.source_document": {"framework_id": "quality.framework"},
    "quality.indicator_def": {
        "edition_id": "quality.framework_edition",
        "source_document_id": "quality.source_document",
    },
    "quality.indicator_value": {"indicator_id": "quality.indicator_def"},
    # Added in step 7. identity.role and identity.user_membership both carry
    # tenant_id as a real foreign key to identity.tenant, which the seeder
    # already satisfies because tenant_id is passed as the row's own tenant.
    "identity.user_membership": {"user_id": "auth.user", "role_id": "identity.role"},
}

#: Supporting rows that must exist before a tenant-owned table can be probed, in
#: insertion order. The identity spine is per tenant because it is tenant-owned;
#: the Quality catalogue spine is global (it has no tenant_id) so one copy
#: suffices for both.
SPINE = (
    "quality.framework",
    "quality.source_document",
    "quality.framework_edition",
    "quality.indicator_def",
)
TENANT_SPINE = (
    "identity.tenant",
    "identity.facility",
    "identity.department",
    "identity.ward",
    "registry.intake_point",
    "identity.role",
    "identity.user_membership",
)


def _insert(connection, table: str, values: dict) -> None:
    """Insert one row from an explicit column -> value mapping."""
    schema, _, name = table.partition(".")
    columns = ", ".join(f'"{column}"' for column in values)
    placeholders = ", ".join(["%s"] * len(values))
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{schema}"."{name}" ({columns}) VALUES ({placeholders})',
            list(values.values()),
        )


@pytest.fixture(scope="module")
def spine(admin_connection):
    """A real identity spine per tenant, so FK constraints hold.

    Every tenant-owned table is truncated first. The database is a long-lived
    test database, and the assertions count rows, so leftovers from a previous
    run would make them order-dependent.

    Returns {tenant_id: {table: row_id}} for the tables in :data:`SPINE`.
    """
    # identity.tenant is excluded from TENANT_OWNED_TABLES (it has no
    # tenant_id), but its rows must still be cleared: the spine seeds fixed ids
    # there, and CASCADE removes the facilities, departments and wards hanging
    # off it.
    to_truncate = ["identity.tenant", *SPINE, *TENANT_SPINE, *TENANT_OWNED_TABLES]
    tables = ", ".join(
        f'"{t.partition(".")[0]}"."{t.partition(".")[2]}"' for t in to_truncate
    )
    with admin_connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {tables} CASCADE")

    created = {}
    stamp = "2026-01-01 00:00:00+00"

    # Django auth has no tenant_id of its own, but identity.user_membership
    # points at it, so a real account row is needed for the FK to hold.
    with admin_connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.auth_user "
            "(id, password, is_superuser, is_staff, is_active, date_joined, "
            " username, first_name, last_name, email) "
            "VALUES (1, '!', false, false, true, %s, %s, '', '', '') "
            "ON CONFLICT (id) DO NOTHING",
            (stamp, f"probe-{uuid.uuid4().hex[:10]}"),
        )
    probe_user_id = 1

    # Global Quality catalogue spine. indicator_value is tenant-owned but points
    # at the global indicator_def, so this row is shared by both tenants.
    global_ids = {}
    for table, extras in (
        ("quality.framework", {"code": "probe-framework", "name": "Probe Framework"}),
        (
            "quality.source_document",
            {"document_name": "Probe source", "document_version": "v0",
             "content_hash": "probe-hash", "imported_at": stamp,
             "licensing_status": "probe"},
        ),
        (
            "quality.framework_edition",
            {"edition": "probe", "effective_from": "2026-01-01", "status": "current"},
        ),
        (
            "quality.indicator_def",
            {"scope_type": "overall", "name": "Probe indicator", "unit": "count",
             "periodicity": "Monthly", "definition": "Probe.", "definition_version": 1,
             "sampling_required": False, "calculation_mode": "auto", "status": "active"},
        ),
    ):
        row_id = uuid.uuid4()
        values = {"id": row_id, **extras}
        for column, parent in _FK_PARENTS.get(table, {}).items():
            values[column] = global_ids[parent]
        _insert(admin_connection, table, values)
        global_ids[table] = row_id

    for tenant_id in (TENANT_A, TENANT_B):
        token = f"spine-{uuid.uuid4().hex[:12]}"
        ids = {}
        _insert(
            admin_connection,
            "identity.tenant",
            {
                "id": tenant_id,
                "name": f"Tenant {token}",
                "slug": f"tenant-{token}",
                "tier": "standard",
                "accreditation_profile": [],
                "db_mode": "shared",
                "created_at": stamp,
            },
        )
        ids["identity.tenant"] = tenant_id

        for table, extras in (
            (
                "identity.facility",
                {"name": f"Facility {token}", "level": "DH",
                 "abdm_registration_status": "pending", "created_at": stamp},
            ),
            (
                "identity.department",
                {"name": f"Department {token}", "opd_enabled": True, "ipd_enabled": True,
                 "active": True, "effective_from": "2026-01-01"},
            ),
            (
                "identity.ward",
                {"name": f"Ward {token}", "type_tag": "Medical", "active": True},
            ),
            (
                "registry.intake_point",
                {"type": "opd", "active": True},
            ),
            # A role per tenant, so identity.user_membership has a tenant-owned
            # role to point at rather than only the platform-wide one.
            (
                "identity.role",
                {"name": f"role-{token}", "permissions": [], "require_mfa": False,
                 "allows_break_glass": False, "created_at": stamp},
            ),
            (
                "identity.user_membership",
                {"active": True},
            ),
        ):
            row_id = uuid.uuid4()
            values = {"id": row_id, "tenant_id": tenant_id, **extras}
            for column, parent in _FK_PARENTS.get(table, {}).items():
                values[column] = _spine_id(
                    {"global": global_ids, "tenants": {tenant_id: ids}, "user": probe_user_id},
                    parent,
                    tenant_id,
                )
            _insert(admin_connection, table, values)
            ids[table] = row_id
        created[tenant_id] = ids
    return {"global": global_ids, "tenants": created, "user": probe_user_id}


def _spine_id(spine: dict, parent: str, tenant_id) -> uuid.UUID:
    """Resolve a parent row id from whichever scope owns it."""
    if parent in spine["global"]:
        return spine["global"][parent]
    if parent == "auth.user":
        return spine["user"]
    return spine["tenants"][tenant_id][parent]


def _probe_statement(connection, table: str, row_id, token: str, tenant_id, spine: dict):
    """Build an INSERT for one probe row.

    Returns (sql, params). Shared by the read tests and the cross-tenant write
    test so both fill required columns identically.
    """
    schema, _, name = table.partition(".")
    fks = _FK_PARENTS.get(table, {})

    columns = ['"id"', '"tenant_id"']
    placeholders = ["%s", "%s"]
    params = [row_id, tenant_id]

    for column, data_type, max_length in _required_columns(connection, table):
        if column in fks:
            # Must reference the spine row for *this* tenant, or the foreign
            # key constraint fails.
            columns.append(f'"{column}"')
            placeholders.append("%s")
            params.append(_spine_id(spine, fks[column], tenant_id))
            continue

        assert data_type in _PROBE_LITERALS, (
            f"{table}.{column} has type {data_type!r}, which the probe-row builder "
            "has no value for. Add it to _PROBE_LITERALS rather than skipping the "
            "table, or the isolation gate silently stops covering it."
        )
        literal = _PROBE_LITERALS[data_type]
        columns.append(f'"{column}"')
        if literal is None:
            placeholders.append("%s")
            if data_type == "uuid":
                params.append(row_id)
            else:
                # Some columns are narrow (blood_group is varchar(8)), so the
                # token is truncated to fit rather than raising.
                params.append(token[:max_length] if max_length else token)
        else:
            placeholders.append(literal)

    return (
        f'INSERT INTO "{schema}"."{name}" ({", ".join(columns)}) '
        f"VALUES ({', '.join(placeholders)})",
        params,
    )


def _seed(connection, table: str, tenant_id, spine: dict) -> uuid.UUID:
    """Insert one probe row for ``tenant_id`` and return its id.

    Every value carries a fresh token so repeated runs cannot collide on a unique
    column such as ``registry.patient.uhid``.
    """
    row_id = uuid.uuid4()
    token = f"probe-{uuid.uuid4().hex[:12]}"
    statement, params = _probe_statement(connection, table, row_id, token, tenant_id, spine)
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
    return row_id


class TestApplicationRoleIsNotPrivileged:
    """Guards the premise of every other test here."""

    def test_role_cannot_bypass_rls(self, admin_connection):
        with admin_connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s",
                (APP_ROLE,),
            )
            row = cursor.fetchone()

        assert row is not None, f"role {APP_ROLE} was not created"
        assert row[0] is False, f"{APP_ROLE} is a superuser and bypasses all RLS"
        assert row[1] is False, f"{APP_ROLE} has BYPASSRLS and ignores all policies"


class TestEveryTenantTableHasAPolicy:
    def test_all_tables_are_protected(self, admin_connection):
        """A table without a policy would return every tenant's rows.

        With RLS enabled and no policy, PostgreSQL denies; the failure this
        guards against is RLS not being enabled at all.
        """
        unprotected = []
        with admin_connection.cursor() as cursor:
            for table in TENANT_OWNED_TABLES:
                schema, _, name = table.partition(".")
                cursor.execute(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = %s AND c.relname = %s",
                    (schema, name),
                )
                row = cursor.fetchone()
                if row is None:
                    unprotected.append(f"{table} (missing)")
                    continue
                if not (row[0] and row[1]):
                    unprotected.append(f"{table} (rls={row[0]}, force={row[1]})")
                    continue
                cursor.execute(
                    "SELECT count(*) FROM pg_policies "
                    "WHERE schemaname = %s AND tablename = %s AND policyname = %s",
                    (schema, name, POLICY_NAME),
                )
                if cursor.fetchone()[0] == 0:
                    unprotected.append(f"{table} (no {POLICY_NAME} policy)")

        assert not unprotected, "tables without enforced tenant isolation:\n" + "\n".join(
            unprotected
        )

    def test_registry_covers_the_expected_volume(self):
        """Guard against the discovery silently returning nothing."""
        assert len(TENANT_OWNED_TABLES) >= 40, TENANT_OWNED_TABLES


class TestCrossTenantReadsFail:
    @pytest.mark.parametrize("table", TENANT_OWNED_TABLES)
    def test_tenant_a_cannot_see_tenant_b_rows(
        self, admin_connection, app_connection, spine, table
    ):
        """Seed both tenants, read as one, assert the other's rows are invisible."""
        schema, _, name = table.partition(".")

        if table not in TENANT_SPINE:
            # Spine rows already exist for both tenants, so adding more would
            # make the count assertion ambiguous rather than stronger.
            _seed(admin_connection, table, TENANT_A, spine)
            _seed(admin_connection, table, TENANT_B, spine)

        _set_tenant(app_connection, TENANT_A)
        with app_connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM "{schema}"."{name}"')
            visible_to_a = cursor.fetchone()[0]

            cursor.execute(
                f'SELECT count(*) FROM "{schema}"."{name}" WHERE tenant_id = %s', (TENANT_B,)
            )
            leaked_to_a = cursor.fetchone()[0]

        assert visible_to_a == 1, (
            f"{table}: tenant A saw {visible_to_a} rows, expected only its own 1"
        )
        assert leaked_to_a == 0, f"{table}: tenant A read {leaked_to_a} tenant B row(s)"


class TestCrossTenantWritesFail:
    @pytest.mark.parametrize("table", TENANT_OWNED_TABLES)
    def test_tenant_a_cannot_write_into_tenant_b(
        self, admin_connection, app_connection, spine, table
    ):
        """WITH CHECK must stop a caller inserting another tenant's row.

        USING alone would permit this: it filters reads, not writes. The probe
        builder supplies every other required column, so the only thing being
        rejected here is the foreign tenant.
        """
        from psycopg import errors

        row_id = uuid.uuid4()
        token = f"probe-{uuid.uuid4().hex[:12]}"
        # Every other required column is filled normally; the only thing that
        # should be rejected is the foreign tenant on tenant_id.
        statement, params = _probe_statement(
            admin_connection, table, row_id, token, TENANT_B, spine
        )

        _set_tenant(app_connection, TENANT_A)
        with pytest.raises((errors.InsufficientPrivilege, errors.CheckViolation)):
            with app_connection.cursor() as cursor:
                cursor.execute(statement, params)


class TestFailsClosedWithoutContext:
    @pytest.mark.parametrize("table", TENANT_OWNED_TABLES)
    def test_no_tenant_context_sees_nothing(
        self, admin_connection, app_connection, spine, table
    ):
        """An unset tenant must yield zero rows, not everything.

        This is the property that stops a forgotten set_config from becoming a
        full data leak.
        """
        schema, _, name = table.partition(".")
        if table not in TENANT_SPINE:
            _seed(admin_connection, table, TENANT_A, spine)

        with app_connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', '', false)")
            cursor.execute(f'SELECT count(*) FROM "{schema}"."{name}"')
            visible = cursor.fetchone()[0]

        assert visible == 0, f"{table}: no tenant context still exposed {visible} row(s)"