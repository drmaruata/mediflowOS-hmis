"""Verify the tenant session setting is actually bound for the whole request.

The unit tests assert the middleware's control flow with the database mocked
out. This module exercises the real mechanism against a live PostgreSQL, because
the original bug was invisible to unit tests: ``set_config(..., is_local=true)``
was issued outside a transaction, which PostgreSQL accepts without complaint
and then silently discards.

Skipped unless a PostgreSQL server is reachable. Point the suite at one with::

    MEDIFLOW_TEST_PGHOST=localhost MEDIFLOW_TEST_PGPORT=5432 \\
    MEDIFLOW_TEST_PGDATABASE=mediflow_test MEDIFLOW_TEST_PGUSER=postgres \\
    MEDIFLOW_TEST_PGPASSWORD=postgres pytest -m integration
"""
import os

import pytest

pytestmark = pytest.mark.integration

PGHOST = os.getenv("MEDIFLOW_TEST_PGHOST")
PGDATABASE = os.getenv("MEDIFLOW_TEST_PGDATABASE", "mediflow_test")
PGUSER = os.getenv("MEDIFLOW_TEST_PGUSER", "postgres")
PGPASSWORD = os.getenv("MEDIFLOW_TEST_PGPASSWORD", "postgres")
PGPORT = os.getenv("MEDIFLOW_TEST_PGPORT", "5432")

requires_postgres = pytest.mark.skipif(
    not PGHOST,
    reason=(
        "set MEDIFLOW_TEST_PGHOST (and companion MEDIFLOW_TEST_PG* variables) "
        "to run tests that assert real PostgreSQL tenant-isolation behaviour"
    ),
)


@pytest.fixture
def postgres_connection():
    """A raw connection to the test PostgreSQL, bypassing project settings."""
    if not PGHOST:
        pytest.skip("MEDIFLOW_TEST_PGHOST not set")

    psycopg = pytest.importorskip("psycopg")

    connection = psycopg.connect(
        host=PGHOST,
        port=PGPORT,
        dbname=PGDATABASE,
        user=PGUSER,
        password=PGPASSWORD,
    )
    try:
        yield connection
    finally:
        connection.close()


@requires_postgres
def test_set_config_local_is_discarded_outside_a_transaction(postgres_connection):
    """Documents the exact failure mode this suite guards against.

    With autocommit on, ``set_config(..., is_local=true)`` applies to an
    implicit single-statement transaction and is reset immediately. This is why
    ``ATOMIC_REQUESTS`` is mandatory and not merely advisory.
    """
    postgres_connection.autocommit = True

    with postgres_connection.cursor() as cursor:
        # A single round trip, so the setting and the read share one implicit
        # transaction. Note that ``is_local = true`` still scopes the setting to
        # that transaction rather than the session, which is exactly why
        # ATOMIC_REQUESTS is required.
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true), current_setting('app.tenant_id')",
            ("tenant-a",),
        )
        _, after_set = cursor.fetchone()

    with postgres_connection.cursor() as cursor:
        # A separate statement, therefore a separate implicit transaction: the
        # previous tenant must be gone.
        cursor.execute("SHOW app.tenant_id")
        after_next_statement = cursor.fetchone()[0]

    assert after_set == "tenant-a"
    assert after_next_statement == ""


@requires_postgres
def test_set_config_local_survives_within_a_transaction(postgres_connection):
    """Inside a transaction the setting persists until commit, as required."""
    with postgres_connection.transaction():
        with postgres_connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", ("tenant-a",))
            cursor.execute("SELECT set_config('app.facility_id', %s, true)", ("facility-1",))
            cursor.execute("SHOW app.tenant_id")
            assert cursor.fetchone()[0] == "tenant-a"
            cursor.execute("SHOW app.facility_id")
            assert cursor.fetchone()[0] == "facility-1"


@requires_postgres
def test_identifier_containing_a_dot_is_a_single_name(postgres_connection):
    """A quoted dotted identifier is one name, not schema-qualified.

    This is the bug the custom schema editor exists to fix: without it Django
    creates a table literally named ``registry.patient`` in ``public``, and
    ``SET CONSTRAINTS`` then cannot resolve the constraint.
    """
    with postgres_connection.transaction():
        with postgres_connection.cursor() as cursor:
            # Dropped first so the test is re-runnable: the failure mode under
            # test aborts the transaction, which would otherwise roll back the
            # cleanup on some exit paths and leave the table behind.
            cursor.execute('DROP TABLE IF EXISTS "schematest"."tbl"')
            cursor.execute('CREATE SCHEMA IF NOT EXISTS "schematest"')
            cursor.execute('CREATE TABLE "schematest"."tbl" (id int PRIMARY KEY)')
            cursor.execute('ALTER TABLE "schematest"."tbl" ADD COLUMN x int')
            cursor.execute(
                'ALTER TABLE "schematest"."tbl" '
                'ADD CONSTRAINT "schematest.tbl_x_fk" FOREIGN KEY (x) '
                'REFERENCES "schematest"."tbl"(id) DEFERRABLE INITIALLY DEFERRED'
            )
            # This is the statement that fails when the constraint lives in a
            # schema missing from search_path.
            cursor.execute('SET search_path TO public, "schematest"')
            cursor.execute('SET CONSTRAINTS "schematest.tbl_x_fk" IMMEDIATE')

            cursor.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'schematest' AND table_name = 'tbl'"
            )
            assert cursor.fetchone()[0] == 1

            cursor.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace "
                "WHERE c.relkind = 'r' AND c.relname LIKE '%.%'"
            )
            assert cursor.fetchone()[0] == 0, "no table should have a dot in its name"


@requires_postgres
def test_constraint_is_unresolvable_when_schema_is_off_the_search_path(
    postgres_connection,
):
    """The precise error the ``search_path`` fix in the schema editor prevents.

    Left as a regression witness: if this ever starts succeeding, the
    ``search_path`` handling in ``common/postgres/schema.py`` has become
    unnecessary, or Django's behaviour changed underneath us.
    """
    with postgres_connection.transaction():
        with postgres_connection.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS "offpath"."t"')
            cursor.execute('CREATE SCHEMA IF NOT EXISTS "offpath"')
            cursor.execute('SET LOCAL search_path TO public')
            cursor.execute('CREATE TABLE "offpath"."t" (id int PRIMARY KEY)')

            with pytest.raises(psycopg_errors_undefined_object(), match="does not exist"):
                cursor.execute(
                    'ALTER TABLE "offpath"."t" ADD COLUMN y int NOT NULL '
                    'CONSTRAINT "offpath.t_y_fk" REFERENCES "offpath"."t"(id) '
                    "DEFERRABLE INITIALLY DEFERRED; "
                    'SET CONSTRAINTS "offpath.t_y_fk" IMMEDIATE'
                )


def psycopg_errors_undefined_object():
    """Resolve the driver's UndefinedObject exception lazily."""
    from psycopg import errors

    return errors.UndefinedObject