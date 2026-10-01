"""Add the RLS migrations (0004) to each tenant-owning app.

Architecture doc section 7 wants row level security on every tenant-owned table,
with CI proving a cross-tenant read fails. RLS is raw DDL with no Django model
state, so it is applied with RunSQL rather than being expressed as a model
option - Django has no first-class way to declare a policy.

The table list is written into each migration explicitly rather than discovered
from the live models, for the same reason makemigrations freezes its state: a
migration must apply the same DDL it applied when it was written.
"""
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parent.parent / "apps"

HEADER = '''# Row level security for tenant-owned tables (architecture doc section 7).
#
# RLS is DDL with no Django model state, so it is applied with RunPython. The
# table list is frozen here rather than discovered from live models, for the same
# reason makemigrations freezes its state: a migration must apply the same DDL
# it applied when it was written.
#
# Applied by scripts/add_rls_migrations.py.
from django.db import migrations

from common import rls
'''

TEMPLATE = '''

#: Tables this app protects. Frozen rather than discovered from live models, so
#: the migration applies the same DDL it applied when it was written.
TABLES = (
{tables}
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
        {dependencies}
    ]

    operations = [
        # RunPython, not RunSQL: Django 5.2's RunSQL accepts SQL strings only,
        # and the quoting here has to come from the live connection.
        migrations.RunPython(forwards, backwards),
    ]
'''

# module -> (tables, depends_on)  where depends_on is the last migration already
# in that app, so RLS is attached after the tenant_id contract migration.
PLAN = {
    "identity_tenancy": (
        ["identity.facility", "identity.department", "identity.ward", "identity.bed",
         "identity.service_unit", "identity.staff_position"],
        "0003_alter_bed_tenant_id_alter_serviceunit_tenant_id_and_more",
    ),
    "patient_registry": (
        ["registry.patient", "registry.intake_point", "registry.qr_code",
         "registry.abdm_callback_log"],
        "0003_alter_intakepoint_tenant_id_alter_qrcode_tenant_id",
    ),
    "opd": (["opd.token", "opd.encounter"], "0003_alter_opdencounter_tenant_id"),
    "ipd": (
        ["ipd.admission", "ipd.census_snapshot", "ipd.bed_status"],
        "0003_alter_bedstatus_tenant_id",
    ),
    "emergency": (["emergency.triage"], "0001_initial"),
    "icu": (["icu.vitals", "icu.device"], "0003_alter_device_tenant_id"),
    "ot": (["ot.schedule", "ot.record"], "0003_alter_surgeryrecord_tenant_id"),
    "lis": (["lis.order", "lis.result"], "0003_alter_labresult_tenant_id"),
    "ris": (["ris.order"], "0001_initial"),
    "pharmacy": (
        ["pharmacy.formulary", "pharmacy.stock_batch", "pharmacy.dispense"],
        "0003_alter_dispense_tenant_id_alter_stockbatch_tenant_id",
    ),
    "blood_bank": (
        ["bbk.donor", "bbk.donation", "bbk.component", "bbk.requisition",
         "bbk.crossmatch", "bbk.reaction"],
        "0003_alter_crossmatch_tenant_id_alter_donation_tenant_id_and_more",
    ),
    "billing_insurance": (
        ["billing.tariff", "billing.invoice", "billing.payment", "billing.claim"],
        "0003_alter_claim_tenant_id_alter_payment_tenant_id",
    ),
    "emr": (
        ["emr.document", "emr.problem", "emr.safety_event"],
        "0003_alter_problemlist_tenant_id",
    ),
    "quality_os": (
        ["quality.indicator_value", "quality.capa", "quality.fact"],
        "0001_initial",
    ),
    "audit": (["audit.event"], "0001_initial"),
    "integration": (["integration.adapter"], "0003_alter_integrationadapter_tenant_id"),
    "platform": (["platform.notification", "platform.feature_flag"], "0001_initial"),
}

FILENAME = "0004_enable_row_level_security.py"


def write(module: str, tables: list[str], previous: str) -> None:
    dependencies = f"(\"{module}\", \"{previous}\"),"
    listing = "\n".join(f'    "{table}",' for table in tables)
    body = TEMPLATE.replace("{tables}", listing).format(dependencies=dependencies)
    path = BACKEND / module / "migrations" / FILENAME
    path.write_text(HEADER + body, encoding="utf-8")


if __name__ == "__main__":
    for name, (tables, previous) in PLAN.items():
        write(name, tables, previous)
        print(f"  {name}/{FILENAME} ({len(tables)} table(s))")
    print(f"{len(PLAN)} RLS migration(s) written")