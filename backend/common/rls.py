"""Row level security for tenant-owned tables.

Architecture doc section 7 specifies shared-schema multi-tenancy enforced in the
database, so that a missing application-side filter cannot leak another
hospital's data. This module generates the DDL; the per-app migrations apply it.

Three details in the SQL are load-bearing, and each corresponds to a way the
policy can silently fail open:

``current_setting('app.tenant_id', true)``
    The two-argument form returns NULL for an unset setting instead of raising.
    The one-argument form raises, which turns a missing tenant context into a
    500 rather than an empty result.

``NULLIF(..., '') IS NOT NULL AND``
    An unset setting arrives as an empty string, and ``''::uuid`` is a cast
    error, not a false predicate. Without the NULLIF guard the policy would
    error rather than deny. With it, no context means no visible rows - the
    policy fails closed.

``FORCE ROW LEVEL SECURITY``
    Table owners bypass RLS by default. Without FORCE, an application role that
    happens to own its tables sees every tenant's rows. FORCE subjects the owner
    to the policies as well.

The one thing SQL cannot fix: superusers and roles with BYPASSRLS bypass all
policies unconditionally, which is why the test suite verifies isolation using a
role with neither attribute rather than trusting the owner.
"""

#: Expression used for both USING and WITH CHECK.
#:
#: USING filters which existing rows a statement may read or modify; WITH CHECK
#: constrains the tenant of rows being written. Both are required: USING alone
#: would let a caller insert a row belonging to another tenant.
TENANT_PREDICATE = """
    NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL
    AND {column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid
""".strip()

POLICY_NAME = "tenant_isolation"

#: Predicate for tables that mix tenant-owned rows with platform-wide ones.
#:
#: ``identity.role`` holds both a hospital's own roles (``tenant`` set) and the
#: platform roles that are global (``tenant`` null, so the platform
#: administrator can onboard tenants per TEN-010). A plain tenant equality
#: predicate would hide the platform roles from everyone, including the
#: administrator who needs them.
PLATFORM_PREDICATE = """
    NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL
    AND (
        {column} IS NULL
        OR {column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )
""".strip()


def _split(db_table: str) -> tuple[str, str]:
    schema, _, table = db_table.partition(".")
    if not table:
        raise ValueError(
            f"{db_table!r} is not schema-qualified; every tenant-owned table must "
            "set an explicit db_table such as 'registry.patient'"
        )
    return schema, table


def enable_table(db_table: str, quote, *, predicate_template: str = TENANT_PREDICATE) -> str:
    """DDL to enable RLS and attach the tenant isolation policy to one table."""
    schema, table = _split(db_table)
    predicate = predicate_template.format(column="tenant_id")

    return f"""
        ALTER TABLE {quote(db_table)} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {quote(db_table)} FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS {quote(POLICY_NAME)} ON {quote(db_table)};
        CREATE POLICY {quote(POLICY_NAME)} ON {quote(db_table)}
            AS PERMISSIVE
            FOR ALL
            USING ({predicate})
            WITH CHECK ({predicate});
    """


def enable_platform_scoped(db_table: str, quote) -> str:
    """Enable RLS on a table holding both tenant-owned and global rows."""
    return enable_table(db_table, quote, predicate_template=PLATFORM_PREDICATE)


def disable_table(db_table: str, quote) -> str:
    """Reverse of :func:`enable_table`.

    RLS is deliberately *not* dropped, only the policy: with RLS enabled and no
    policy, PostgreSQL applies a default-deny, which is the safe state to leave
    a table in. Dropping RLS as well would briefly open the table entirely.
    """
    return f"DROP POLICY IF EXISTS {quote(POLICY_NAME)} ON {quote(db_table)};"


def enable(tables: list[str], quote) -> str:
    return "".join(enable_table(table, quote) for table in tables)


def disable(tables: list[str], quote) -> str:
    return "".join(disable_table(table, quote) for table in tables)