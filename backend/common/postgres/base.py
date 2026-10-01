"""Database wrapper and operations with schema-aware identifier quoting.

Everything here is inherited from ``django.db.backends.postgresql``. The two
changes are:

* ``DatabaseOperations.quote_name`` treats a dotted name that exactly matches a
  declared ``db_table`` as a schema qualifier, so ``db_table =
  "registry.patient"`` refers to table ``patient`` in schema ``registry``
  rather than a table literally named ``registry.patient``.
* ``DatabaseWrapper`` uses a schema editor that emits ``CREATE SCHEMA`` and
  keeps module schemas on ``search_path`` during migrations.

See :mod:`common.postgres.quoting` for why the split is restricted to exact
table-name matches.
"""
from django.db.backends.postgresql import base

from .quoting import quote_qualified
from .schema import SchemaQualifiedSchemaEditor

__all__ = ["DatabaseWrapper", "DatabaseOperations"]


class DatabaseOperations(base.DatabaseOperations):
    _quote_name_impl = base.DatabaseOperations.quote_name

    def quote_name(self, name):
        # Route through the stock implementation for anything that is not a
        # schema-qualified table name, including the schema and table halves of
        # one that is.
        return quote_qualified(self._quote_name_impl, name)


class DatabaseWrapper(base.DatabaseWrapper):
    SchemaEditorClass = SchemaQualifiedSchemaEditor

    ops_class = DatabaseOperations