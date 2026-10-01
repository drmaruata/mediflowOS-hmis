"""Schema editor for schema-per-module table placement.

Kept separate from :mod:`common.postgres.base` to mirror the layout of Django's
own PostgreSQL backend. Identifier quoting itself is inherited, because
:class:`common.postgres.base.DatabaseOperations` already handles it; this
editor adds the DDL that PostgreSQL needs for the schemas to exist.
"""
from django.db.backends.postgresql import base

from .quoting import module_schemas


class SchemaQualifiedSchemaEditor(base.DatabaseSchemaEditor):
    """Create module schemas, and keep them resolvable while migrating."""

    def table_sql(self, model):
        """Emit ``CREATE SCHEMA`` before the table that lives inside it."""
        db_table = model._meta.db_table
        if "." in db_table:
            schema, _, _ = db_table.partition(".")
            self.execute(
                f"CREATE SCHEMA IF NOT EXISTS {self.connection.ops.quote_name(schema)}"
            )
        return super().table_sql(model)

    def _search_path_sql(self) -> str:
        schemas = ["public", *module_schemas()]
        quoted = ", ".join(self.connection.ops.quote_name(name) for name in schemas)
        return f"SET search_path TO {quoted}"

    def __enter__(self):
        result = super().__enter__()

        # PostgreSQL resolves a bare constraint name in ``SET CONSTRAINTS``
        # through ``search_path``. Django's postgres backend pairs that
        # statement with ``ALTER TABLE ... ADD CONSTRAINT`` so the check can be
        # relaxed within the same transaction, but it passes the constraint name
        # unqualified. Once tables live in a module schema that is missing from
        # ``search_path``, the lookup fails and the migration aborts with
        # ``constraint "..." does not exist`` immediately after creating it.
        # Putting the module schemas on the path for the duration of schema
        # editing makes both statements resolve to the same relation.
        if self.collect_sql:
            # Keep `sqlmigrate` output faithful rather than silently omitting
            # the statement real migrations depend on.
            self.execute(self._search_path_sql())
            return result

        self._previous_search_path = self._capture_search_path()
        self.connection.cursor().execute(self._search_path_sql())
        return result

    def _capture_search_path(self) -> str:
        with self.connection.cursor() as cursor:
            cursor.execute("SHOW search_path")
            return cursor.fetchone()[0]

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if not self.collect_sql:
                # Restore the session path so a pooled connection is not left
                # pointing at module schemas the caller did not ask for.
                with self.connection.cursor() as cursor:
                    cursor.execute(f"SET search_path TO {self._previous_search_path}")
        finally:
            return super().__exit__(exc_type, exc_value, traceback)