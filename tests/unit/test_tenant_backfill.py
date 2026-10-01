"""Backfill helper logic, exercised without any external service.

The step-5 migration adds ``tenant_id`` to 20 tables. For any table that already
held rows, the column is added nullable, backfilled from the owning parent, and
only then tightened to NOT NULL. That makes the backfill the step where a wrong
tenant could be written, so it is tested directly rather than inferred from a
successful migration on an empty database.

These run against the SQLite test database using purpose-built scratch tables,
which keeps ``config.settings.test`` free of external services. The
schema-qualified variant - the case where ``quote_name`` must split
``"identity.ward"`` into ``"identity"."ward"`` - is covered separately by
``tests/integration/test_postgres_schema.py``, because splitting only happens on
PostgreSQL.
"""
import uuid

import pytest
from django.db import connection, transaction

from common.tenant_migration import assert_no_orphans, backfill_tenant_id, require_empty

# These build real scratch tables, so they need database access. They stay on
# the in-memory SQLite database, so no external service is involved.
pytestmark = [pytest.mark.unit, pytest.mark.django_db]

PARENT_TABLE = "backfill_parent"
CHILD_TABLE = "backfill_child"

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def scratch():
    """Two tables shaped like a tenant-owned parent and its child."""
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {CHILD_TABLE}")
        cursor.execute(f"DROP TABLE IF EXISTS {PARENT_TABLE}")
        cursor.execute(
            f"CREATE TABLE {PARENT_TABLE} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)"
        )
        cursor.execute(
            f"CREATE TABLE {CHILD_TABLE} "
            "(id uuid PRIMARY KEY, parent_id uuid, tenant_id uuid NULL)"
        )
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {CHILD_TABLE}")
            cursor.execute(f"DROP TABLE IF EXISTS {PARENT_TABLE}")


def _insert(table: str, **columns) -> str:
    row_id = str(uuid.uuid4())
    names = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} (id, {names}) VALUES (%s, {placeholders})",
            [row_id, *columns.values()],
        )
    return row_id


def _tenant_of(table: str, row_id: str):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT tenant_id FROM {table} WHERE id = %s", [row_id])
        value = cursor.fetchone()[0]
    return str(value) if value is not None else None


class TestBackfillCopiesTheParentsTenant:
    def test_child_inherits_the_owning_tenant(self, scratch):
        parent_id = _insert(PARENT_TABLE, tenant_id=TENANT_A)
        child_id = _insert(CHILD_TABLE, parent_id=parent_id)

        backfill_tenant_id(
            target_table=CHILD_TABLE,
            parent_table=PARENT_TABLE,
            parent_column="parent_id",
        )
        assert_no_orphans(target_table=CHILD_TABLE)

        assert _tenant_of(CHILD_TABLE, child_id) == TENANT_A

    def test_rows_of_different_tenants_do_not_cross(self, scratch):
        """Two children under different parents keep different tenants."""
        first_parent = _insert(PARENT_TABLE, tenant_id=TENANT_A)
        second_parent = _insert(PARENT_TABLE, tenant_id=TENANT_B)
        first_child = _insert(CHILD_TABLE, parent_id=first_parent)
        second_child = _insert(CHILD_TABLE, parent_id=second_parent)

        backfill_tenant_id(
            target_table=CHILD_TABLE,
            parent_table=PARENT_TABLE,
            parent_column="parent_id",
        )

        assert _tenant_of(CHILD_TABLE, first_child) == TENANT_A
        assert _tenant_of(CHILD_TABLE, second_child) == TENANT_B


class TestBackfillDoesNotOverwrite:
    def test_an_existing_tenant_is_left_alone(self, scratch):
        """Re-running the migration must not move a row between tenants.

        The UPDATE is restricted to NULL rows precisely so a replay is safe.
        """
        parent_id = _insert(PARENT_TABLE, tenant_id=TENANT_B)
        child_id = _insert(CHILD_TABLE, parent_id=parent_id, tenant_id=TENANT_A)

        backfill_tenant_id(
            target_table=CHILD_TABLE,
            parent_table=PARENT_TABLE,
            parent_column="parent_id",
        )

        assert _tenant_of(CHILD_TABLE, child_id) == TENANT_A


class TestBackfillRefusesToGuess:
    def test_a_row_with_no_parent_fails_the_migration(self, scratch):
        """An unresolvable row must stop the migration, not be defaulted.

        Defaulting would write a plausible-looking tenant onto a clinical row,
        which is the cross-tenant leakage the architecture doc section 7 calls
        the top risk.
        """
        _insert(CHILD_TABLE, parent_id=None)

        backfill_tenant_id(
            target_table=CHILD_TABLE,
            parent_table=PARENT_TABLE,
            parent_column="parent_id",
        )

        with pytest.raises(RuntimeError, match="still have a NULL tenant_id"):
            assert_no_orphans(target_table=CHILD_TABLE)

    def test_a_row_pointing_at_a_missing_parent_fails(self, scratch):
        _insert(CHILD_TABLE, parent_id=str(uuid.uuid4()))

        backfill_tenant_id(
            target_table=CHILD_TABLE,
            parent_table=PARENT_TABLE,
            parent_column="parent_id",
        )

        with pytest.raises(RuntimeError, match="still have a NULL tenant_id"):
            assert_no_orphans(target_table=CHILD_TABLE)

    def test_require_empty_accepts_an_empty_table(self, scratch):
        require_empty(target_table=CHILD_TABLE)

    def test_require_empty_rejects_a_populated_table(self, scratch):
        """integration.adapter has no parent, so its rows are unresolvable."""
        _insert(CHILD_TABLE, parent_id=None)

        with pytest.raises(RuntimeError, match="has no parent row"):
            require_empty(target_table=CHILD_TABLE)


class TestHelperIsTransactionSafe:
    def test_backfill_runs_inside_the_caller_transaction(self, scratch):
        """The helper must not commit on its own.

        Migration callers rely on the surrounding atomic block; an internal
        commit would defeat the expand/contract rollback story.
        """
        parent_id = _insert(PARENT_TABLE, tenant_id=TENANT_A)
        child_id = _insert(CHILD_TABLE, parent_id=parent_id)

        with pytest.raises(RuntimeError):
            with transaction.atomic():
                backfill_tenant_id(
                    target_table=CHILD_TABLE,
                    parent_table=PARENT_TABLE,
                    parent_column="parent_id",
                )
                assert _tenant_of(CHILD_TABLE, child_id) == TENANT_A
                # Forcing the outer block to roll back must undo the backfill.
                raise RuntimeError("rollback")

        assert _tenant_of(CHILD_TABLE, child_id) is None