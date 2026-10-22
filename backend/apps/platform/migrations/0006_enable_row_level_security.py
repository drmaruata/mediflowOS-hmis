# Row level security for tenant-owned tables (architecture doc section 7).
#
# RLS is DDL with no Django model state, so it is applied with RunPython. The
# table list is frozen here rather than discovered from live models, for the same
# reason makemigrations freezes its state: a migration must apply the same DDL
# it applied when it was written.
#
# platform.file post-dates 0004 (the table was created in 0005, after that
# migration was written), so the app's original RLS migration never named it and
# this table has had no policy since it existed. That is the exact failure
# architecture doc section 7 warns about: with RLS off, the table answers every
# tenant's rows to any caller whose application-side filter is missing, and
# ``makemigrations --check`` says nothing because there is no model state.
#
# A standalone migration rather than an edit to 0004, for the reason every
# applied migration is left alone: 0004 has already run somewhere, and a later
# environment that applied the edited file would end up with different DDL from
# one that applied the original.
#
# Applied by scripts/add_rls_migrations.py.
from django.db import migrations

from common import rls


#: Tables this app protects. Frozen rather than discovered from live models, so
#: the migration applies the same DDL it applied when it was written.
TABLES = (
    "platform.file",
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
        ("platform", "0005_platformfile_scheduledjob_delete_featureflag_and_more"),
    ]

    operations = [
        # RunPython, not RunSQL: Django 5.2's RunSQL accepts SQL strings only,
        # and the quoting here has to come from the live connection.
        migrations.RunPython(forwards, backwards),
    ]
