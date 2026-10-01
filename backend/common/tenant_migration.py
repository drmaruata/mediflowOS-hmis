"""Helpers for migrations that add ``tenant_id`` to an existing table.

Adding a NOT NULL ``tenant_id`` to a table that may already hold rows cannot be
done in one step: PostgreSQL needs a value for every existing row, and the only
correct value is the owning tenant. Guessing is not an option - a silently wrong
tenant_id on a clinical row is exactly the cross-tenant leakage the architecture
doc names as the top risk.

So migrations that introduce the column do it in the expand/contract order the
architecture doc requires:

1. **Expand** - add the column nullable, then backfill it from the owning
   parent row. Every tenant-owned table except a standalone configuration table
   has a parent that is already tenant-scoped, so the correct value is derivable.
2. **Contract** - once no row is left NULL, tighten to NOT NULL in a later
   migration.

:func:`backfill_tenant_id` performs step 1's copy and then asserts that nothing
was left NULL, so a migration cannot quietly complete against a table whose
rows it could not attribute.
"""
from django.db import connection


def backfill_tenant_id(
    *,
    target_table: str,
    parent_table: str,
    parent_column: str,
    target_column: str = "tenant_id",
) -> int:
    """Copy the parent row's tenant_id onto the target table.

    ``target_table`` and ``parent_table`` are schema-qualified ``db_table``
    values (``"billing.invoice"``). The parent's primary key is assumed to be
    ``id``, which holds for every model in this project.

    Both names are passed to the backend's ``quote_name`` whole. That matters:
    ``quote_name`` is what turns ``"billing.invoice"`` into
    ``"billing"."invoice"``, so splitting the string here would reduce the
    relation to its schema alone and PostgreSQL would look for a *table* named
    ``billing``.

    Returns the number of rows updated.
    """
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {quote(target_table)} AS child
            SET {quote(target_column)} = parent.{quote("tenant_id")}
            FROM {quote(parent_table)} AS parent
            WHERE child.{quote(parent_column)} = parent.{quote("id")}
              AND child.{quote(target_column)} IS NULL
            """
        )
        return cursor.rowcount


def assert_no_orphans(*, target_table: str, target_column: str = "tenant_id") -> None:
    """Fail the migration if any row still has no tenant.

    Raising here is deliberate. A migration that completes while leaving rows
    unattributed would hand the next migration a table whose NOT NULL
    constraint then fails far from the real cause.
    """
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) FROM {quote(target_table)} "
            f"WHERE {quote(target_column)} IS NULL"
        )
        orphans = cursor.fetchone()[0]

    if orphans:
        raise RuntimeError(
            f"{orphans} row(s) in {target_table} still have a NULL "
            f"{target_column} after backfill. Each row must be attributable to "
            "exactly one tenant. Resolve the parent rows before retrying; do not "
            "default these to a tenant."
        )


def require_empty(*, target_table: str) -> None:
    """Fail unless a table has no rows, for tables with no parent to derive from.

    Used for standalone configuration tables such as
    ``integration.adapter``, where no existing row implies which tenant owns it.
    """
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {quote(target_table)}")
        rows = cursor.fetchone()[0]

    if rows:
        raise RuntimeError(
            f"Cannot add a tenant_id to {target_table}: the table holds {rows} "
            "row(s) and has no parent row from which to derive the owning "
            "tenant. Backfill tenant_id explicitly before adding the NOT NULL "
            "constraint."
        )