# Row level security for tenant-owned tables (architecture doc section 7).
#
# RLS is DDL with no Django model state, so it is applied with RunPython. The
# table list is frozen here rather than discovered from live models, for the same
# reason makemigrations freezes its state: a migration must apply the same DDL
# it applied when it was written.
#
# Applied by scripts/add_rls_migrations.py.
from django.db import migrations

from common import rls


#: Tables this app protects. Frozen rather than discovered from live models, so
#: the migration applies the same DDL it applied when it was written.
TABLES = (
    "ris.order",
)


def _is_postgres(schema_editor) -> bool:
    # Django has no feature flag for row level security, so the backend is
    # checked directly. The fast test suite runs on in-memory SQLite, which has
    # no RLS and no ALTER TABLE ... ENABLE syntax; without this guard the test
    # database cannot even be created. SQLite also has no equivalent, so tenant
    # isolation there is enforced by TenantScopedQuerysetMixin alone - which is
    # why the isolation gate in tests/integration/test_rls_isolation.py requires
    # a real PostgreSQL.
    return schema_editor.connection.vendor == "postgresql"


def forwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    schema_editor.execute(rls.enable(TABLES, schema_editor.connection.ops.quote_name))


def backwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    # Drops the policy but leaves RLS enabled, so the table ends up in
    # PostgreSQL's default-deny state rather than briefly wide open.
    schema_editor.execute(rls.disable(TABLES, schema_editor.connection.ops.quote_name))


class Migration(migrations.Migration):

    dependencies = [
        ("ris", "0001_initial"),
    ]

    operations = [
        # RunPython, not RunSQL: Django 5.2's RunSQL accepts SQL strings only,
        # and the quoting here has to come from the live connection.
        migrations.RunPython(forwards, backwards),
    ]
