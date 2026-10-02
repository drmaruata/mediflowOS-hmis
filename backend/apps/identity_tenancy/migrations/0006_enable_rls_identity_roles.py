# Row level security for the identity tables added in step 7.
#
# Separate from 0004_enable_row_level_security because that migration is already
# committed; a new migration is the correct way to extend protection rather than
# editing an applied one.
#
# identity.role needs the platform-scoped predicate: it holds a hospital's own
# roles (tenant set) alongside global platform roles (tenant null) that the
# platform administrator needs in order to onboard tenants (TEN-010). The other
# two are ordinary tenant-owned tables.
from django.db import migrations

from common import rls

PLATFORM_SCOPED = ("identity.role",)
TENANT_OWNED = ("identity.user_membership", "identity.break_glass_access")


def _is_postgres(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql"


def forwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    quote = schema_editor.connection.ops.quote_name
    for table in PLATFORM_SCOPED:
        schema_editor.execute(rls.enable_platform_scoped(table, quote))
    # enable() takes a collection, not a single name - passing a bare string
    # would iterate it character by character.
    for table in TENANT_OWNED:
        schema_editor.execute(rls.enable([table], quote))


def backwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    quote = schema_editor.connection.ops.quote_name
    # Drops the policies but leaves RLS enabled, so these tables land in
    # PostgreSQL's default-deny state rather than briefly wide open.
    for table in (*PLATFORM_SCOPED, *TENANT_OWNED):
        schema_editor.execute(rls.disable(table, quote))


class Migration(migrations.Migration):

    dependencies = [
        ("identity_tenancy", "0005_breakglassaccess_role_usermembership_and_more"),
        ("identity_tenancy", "0004_enable_row_level_security"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]