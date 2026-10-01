"""Schema-aware identifier quoting shared by the backend and its schema editor.

Kept in its own module so both :mod:`common.postgres.base` and
:mod:`common.postgres.schema` can use it without importing each other.
"""
from django.apps import apps


def qualified_table_names() -> frozenset:
    """Every ``db_table`` in the project that carries a schema qualifier.

    Cached on the app registry, which is the natural owner: the set can only
    change when models do, and app loading happens once per process.
    """
    cached = getattr(apps, "_mediflow_qualified_tables", None)
    if cached is None:
        cached = frozenset(
            model._meta.db_table
            for model in apps.get_models()
            if "." in model._meta.db_table
        )
        apps._mediflow_qualified_tables = cached
    return cached


def module_schemas() -> list:
    """Module schemas declared by the models, in a stable order."""
    return sorted({name.partition(".")[0] for name in qualified_table_names()})


def quote_qualified(quote, name: str) -> str:
    """Quote a name, treating ``schema.table`` as a schema qualifier.

    ``quote`` is the unmodified backend quoting function, so this helper never
    recurses back into itself.

    Only names that *exactly* match a declared ``db_table`` are split. That
    restriction is load-bearing: Django derives index names and foreign key
    constraint names from ``db_table``, so an index on ``registry.patient``
    is called ``registry.patient_tenant_id_uhid_9f3a1c_idx``. Splitting that
    would truncate the index name, and for a cross-module foreign key would
    emit ``ALTER TABLE ... ADD CONSTRAINT "schema"."name"``, which PostgreSQL
    rejects outright.

    Everything else - column names, index names, constraint names, Django's
    own tables in ``public`` - is quoted verbatim.
    """
    if name in qualified_table_names():
        schema, _, table = name.partition(".")
        return f"{quote(schema)}.{quote(table)}"
    return quote(name)