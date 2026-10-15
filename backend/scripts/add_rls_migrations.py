"""Add the RLS migrations (0004) to each tenant-owning app.

Architecture doc section 7 wants row level security on every tenant-owned table,
with CI proving a cross-tenant read fails. RLS is raw DDL with no Django model
state, so it is applied with RunSQL rather than being expressed as a model
option - Django has no first-class way to declare a policy.

The table list is written into each migration explicitly rather than discovered
from the live models, for the same reason makemigrations freezes its state: a
migration must apply the same DDL it applied when it was written.
"""
import importlib
import pathlib
from dataclasses import dataclass

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
#
# ``platform`` is listed with its *original* table pair and 0001, because this
# registry describes the 0004 migration each app already has. A table created
# after its app's 0004 was written cannot be named by that 0004 - rewriting it
# to name the table would fork the applied history - so every such table is
# absent from PLAN and registered in STANDALONE below instead, with
# UNPROTECTED_TABLES recording the tenant-owned tables that deliberately have no
# policy. PLAN is what ``__main__`` *writes*, so anything here is a claim about
# an applied migration - ``verify_plan`` is the check that keeps that claim true.
PLAN = {
    "identity_tenancy": (
        ["identity.facility", "identity.department", "identity.ward", "identity.bed",
         "identity.service_unit", "identity.staff_position"],
        "0003_alter_bed_tenant_id_alter_serviceunit_tenant_id_and_more",
    ),
    "patient_registry": (
        ["registry.patient", "registry.intake_point", "registry.qr_code"],
        "0003_alter_intakepoint_tenant_id_alter_qrcode_tenant_id",
    ),
    "abdm_gateway": (
        ["abdm.callback_log"],
        "0001_initial",
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


@dataclass(frozen=True)
class StandaloneEntry:
    """One RLS migration that cannot live in an app's ``0004``.

    ``filename`` is the migration file in ``<module>/migrations/``,
    ``previous`` the migration it depends on, and ``tables`` the frozen table
    list that migration must declare.

    ``declarations`` names the migration attributes ``tables`` is read from,
    concatenated in that order, and defaults to the ``TABLES`` tuple the
    generated migrations all use. It exists for the one migration whose policy
    is not uniform - ``identity.role`` is platform-scoped rather than
    tenant-owned, so it lists its tables under two names - and naming the
    attributes rather than special-casing the file keeps the check uniform: a
    migration that forgets to declare its tables is reported the same way
    whichever shape it uses.

    ``additional_previous`` records any further migrations the file depends on.
    ``previous`` alone would be a partial record for a migration that declares
    two dependencies, and a registry that pins half an ordering does not pin it.

    Metadata only. Nothing in this script writes a standalone migration - they
    are hand-written, or generated once and committed - so registering an entry
    records where a table is protected without emitting anything.
    """

    filename: str
    previous: str
    tables: tuple[str, ...]
    declarations: tuple[str, ...] = ("TABLES",)
    additional_previous: tuple[str, ...] = ()


#: Tables added to an app *after* its 0004 RLS migration was written.
#:
#: They cannot go in PLAN. Re-running this script overwrites every 0004 it
#: generates, so a table listed there would rewrite an already-applied migration
#: to name a table that did not exist when it was first applied - an environment
#: that ran the original file would end up without the policy, silently, while
#: one that ran the rewritten file has it. The two histories diverge and nothing
#: reports it, because RLS is DDL with no model state and ``makemigrations
#: --check`` has nothing to compare.
#:
#: So these get their own migration, depend on the last real migration before
#: them, and are registered here anyway: this registry is what a later reader -
#: or the person adding the next tenant-owned table to the same app - consults
#: to find out that the table is covered somewhere other than 0004. Keyed by
#: module because an app can accumulate several of these (identity_tenancy has
#: four), each in its own migration.
#:
#: Two shapes are registered, and both satisfy the same contract the check
#: below asserts (the attributes a migration declares its protected tables in,
#: and the migrations it depends on):
#:
#: - a dedicated RLS-only migration, attached after the migration that created
#:   the table - the ``platform`` and the ``identity.role`` entries;
#: - RLS attached inside the model migration that creates the table, which is
#:   one migration rather than two for a table that does not exist yet, and the
#:   pattern the ``abdm_gateway``, ``opd``, ``patient_registry`` and the later
#:   ``identity_tenancy`` entries use.
#:
#: Named by entry rather than by file number on purpose: a bare "same as
#: identity_tenancy 0007" is a claim about a filename that nothing verifies,
#: which is how this registry drifted in the first place - six tables across
#: three apps had a policy attached in their own migration and appeared in no
#: registry at all. ``tests/unit/test_rls_migration_registry.py`` now holds the
#: registry to the migrations themselves, so the next one fails the suite.
STANDALONE = {
    "abdm_gateway": (
        StandaloneEntry(
            filename="0005_abhacallbacklog_link_token_enc_consentevent.py",
            previous="0004_enable_row_level_security",
            tables=("abdm.consent_event",),
        ),
    ),
    "platform": (
        StandaloneEntry(
            filename="0006_enable_row_level_security.py",
            previous="0005_platformfile_scheduledjob_delete_featureflag_and_more",
            tables=("platform.file",),
        ),
    ),
    "identity_tenancy": (
        # The one migration whose policy is not uniform: ``identity.role`` holds
        # a hospital's roles alongside global platform roles with a null tenant,
        # so it gets the platform-scoped predicate and the other two get the
        # ordinary tenant-owned one. Two declarations, two dependencies - both
        # recorded, because half an ordering is not an ordering.
        StandaloneEntry(
            filename="0006_enable_rls_identity_roles.py",
            previous="0005_breakglassaccess_role_usermembership_and_more",
            tables=("identity.role", "identity.user_membership",
                    "identity.break_glass_access"),
            declarations=("PLATFORM_SCOPED", "TENANT_OWNED"),
            additional_previous=("0004_enable_row_level_security",),
        ),
        StandaloneEntry(
            filename="0007_setupprogress.py",
            previous="0006_enable_rls_identity_roles",
            tables=("identity.setup_progress",),
        ),
        StandaloneEntry(
            filename="0008_baselineinput_referencedata.py",
            previous="0007_setupprogress",
            tables=("identity.reference_data", "identity.baseline_input"),
        ),
        StandaloneEntry(
            filename="0009_configrevision_and_bed_active.py",
            previous="0008_baselineinput_referencedata",
            tables=("identity.config_revision",),
        ),
    ),
    "opd": (
        StandaloneEntry(
            filename="0005_tokenseries.py",
            previous="0004_enable_row_level_security",
            tables=("opd.token_series",),
        ),
    ),
    "patient_registry": (
        StandaloneEntry(
            filename="0007_patientsequence.py",
            previous="0006_patient_verified_at",
            tables=("registry.sequence",),
        ),
    ),
}

#: Tenant-owned tables that deliberately have no RLS policy, and why.
#:
#: Recorded here so the registry answers for every tenant-owned table rather
#: than only the ones with a policy: a table absent from both PLAN and
#: STANDALONE is otherwise indistinguishable from one nobody got round to.
#: This is a record, not a work item - adding a policy is a deliberate decision
#: with its own migration, and nothing here emits one.
UNPROTECTED_TABLES = {
    # Written by Celery, read through the worker's own scoping. See
    # backend/apps/workers/tasks.py, the ``run_scheduled_job`` docstring:
    # application scoping is the only control on this table.
    "platform.scheduled_job": (
        "deliberate - scoped by the worker; see backend/apps/workers/tasks.py"
    ),
}


def standalone_entries() -> tuple[tuple[str, StandaloneEntry], ...]:
    """Every registered entry as ``(module, entry)``, in a stable order.

    Flat because that is how both callers want it: the verifier checks each one,
    and the run summary counts them. An app with several entries contributes
    several pairs, so the count is of migrations and not of apps.
    """
    return tuple(
        (module, entry)
        for module, entries in STANDALONE.items()
        for entry in entries
    )


def standalone_tables() -> dict[str, tuple[str, StandaloneEntry]]:
    """Every registered table mapped to the entry that protects it.

    The lookup the registry exists for: given a table, where is its policy? It
    raises on a duplicate rather than overwriting, because a table claimed twice
    is either two migrations racing to enable the same policy or one of them
    stale, and both are silent.
    """
    found: dict[str, tuple[str, StandaloneEntry]] = {}
    for module, entry in standalone_entries():
        for table in entry.tables:
            if table in found:
                raise ValueError(f"{table} is registered twice in STANDALONE")
            found[table] = (module, entry)
    return found


def _ensure_django() -> None:
    """Configure Django so the checks below can import migration modules.

    Importing one executes ``from common import rls``, which needs the settings
    module loaded. ``setup()`` reads configuration and builds the app registry;
    it opens no database connection, so running this script still cannot touch
    one. An explicit ``DJANGO_SETTINGS_MODULE`` in the environment wins, which
    is how the pytest suite reaches these functions under
    ``config.settings.test``.

    The project root goes on ``sys.path`` first because this file is run by
    path, which puts ``scripts/`` there and not ``backend/`` - so ``config``
    and ``apps`` would otherwise be unimportable.
    """
    import os
    import sys

    root = str(BACKEND.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django

    django.setup()


def _migration_module(module: str, filename: str):
    """Import one migration module by app and filename, or ``None``.

    Migration module names begin with a digit, so they cannot be reached by an
    ``import`` statement - ``import_module`` is the only way in, and every check
    below needs it.
    """
    try:
        return importlib.import_module(
            f"apps.{module}.migrations.{filename[: -len('.py')]}"
        )
    except ImportError:
        return None


def verify_plan() -> tuple[str, ...]:
    """Check every PLAN entry still matches the 0004 migration on disk.

    Returns the problems found, empty when the registry and the applied files
    agree. This is the check ``__main__`` runs before it writes anything,
    because the hazard is asymmetric and silent: ``write()`` regenerates all 18
    files unconditionally, and a PLAN entry that has drifted from its migration
    is rewritten to name a different set of tables than the one that was
    applied. Nothing downstream notices - RLS is DDL with no model state, so
    ``makemigrations --check`` has nothing to compare and an environment that
    already ran the original file keeps the original policy forever.

    Three things are compared per entry, because each can drift on its own:
    the frozen table list, the migration the entry depends on, and the rendered
    file itself. The last one is what answers the question the other two exist
    to support - "if this script ran right now, would it rewrite an applied
    migration?" - and it also catches the template drifting away from the files
    it is supposed to have produced.
    """
    problems = []
    for module, (tables, previous) in PLAN.items():
        path = BACKEND / module / "migrations" / FILENAME
        if not path.exists():
            problems.append(f"{module}/{FILENAME}: missing")
            continue
        migration = _migration_module(module, FILENAME)
        if migration is None:
            problems.append(f"{module}/{FILENAME}: not importable")
            continue
        declared = tuple(migration.TABLES)
        if declared != tuple(tables):
            problems.append(
                f"{module}/{FILENAME}: declares {declared}, PLAN says {tuple(tables)}"
            )
        dependencies = tuple(tuple(dep) for dep in migration.Migration.dependencies)
        if (module, previous) not in dependencies:
            problems.append(
                f"{module}/{FILENAME}: depends on {dependencies}, "
                f"PLAN says {previous}"
            )
        if path.read_text(encoding="utf-8") != _render(module, tables, previous):
            problems.append(
                f"{module}/{FILENAME}: on disk differs from what this script writes"
            )
    return tuple(problems)


def verify_standalone() -> tuple[str, ...]:
    """Check each standalone migration matches what the registry claims about it.

    Returns the problems found, empty when the registry and the files on disk
    agree. Three things are compared per entry, for the same reasons
    :func:`verify_plan` compares three: the frozen table list, the migration the
    entry depends on, and - through the first two - that the file is really
    there and really is a migration.

    The dependency check is the one that was missing. ``previous`` is recorded
    as the migration an entry follows, and nothing used it: an entry naming a
    migration that is not among its dependencies would pass every other check,
    so the registry would assert an ordering the applied migrations do not have.
    For the attached-in-the-model-migration shape - where RLS runs in the same
    ``RunPython`` that creates the table - a wrong ``previous`` means the
    policy is attached before the table exists, which is a migration that fails
    on PostgreSQL and silently does nothing on SQLite.

    Every recorded predecessor is checked, not just ``previous``, so an entry
    listing a second dependency is held to it too.

    Unlike PLAN, an entry here is never rewritten by a run, so the failure mode
    is a false record rather than a divergent history. It still has to be caught
    where the claim is made.
    """
    problems = []
    for module, entry in standalone_entries():
        path = BACKEND / module / "migrations" / entry.filename
        if not path.exists():
            problems.append(f"{module}/{entry.filename}: missing")
            continue
        migration = _migration_module(module, entry.filename)
        if migration is None:
            problems.append(f"{module}/{entry.filename}: not importable")
            continue
        missing = [
            attribute
            for attribute in entry.declarations
            if not hasattr(migration, attribute)
        ]
        if missing:
            problems.append(
                f"{module}/{entry.filename}: declares no {missing[0]!r}"
            )
        else:
            declared = tuple(
                table
                for attribute in entry.declarations
                for table in getattr(migration, attribute)
            )
            if declared != entry.tables:
                problems.append(
                    f"{module}/{entry.filename}: declares {declared}, "
                    f"registry says {entry.tables}"
                )
        dependencies = tuple(tuple(dep) for dep in migration.Migration.dependencies)
        for expected in (entry.previous, *entry.additional_previous):
            if (module, expected) not in dependencies:
                problems.append(
                    f"{module}/{entry.filename}: depends on {dependencies}, "
                    f"registry says {expected}"
                )
    return tuple(problems)


def _render(module: str, tables: list[str], previous: str) -> str:
    """The exact text ``write()`` would put on disk for one PLAN entry.

    Shared with :func:`verify_plan` so that the comparison is against what this
    script would write *now*, not a second copy of the template that could drift
    from the first.
    """
    dependencies = f"(\"{module}\", \"{previous}\"),"
    listing = "\n".join(f'    "{table}",' for table in tables)
    body = TEMPLATE.replace("{tables}", listing).format(dependencies=dependencies)
    return HEADER + body


def write(module: str, tables: list[str], previous: str) -> None:
    path = BACKEND / module / "migrations" / FILENAME
    path.write_text(_render(module, tables, previous), encoding="utf-8")


if __name__ == "__main__":
    _ensure_django()
    # Verified before anything is written, not after: the point of the check is
    # to stop the rewrite, and a check that runs afterwards has already let it
    # happen. Every entry is reported by name rather than only as a count,
    # because "17 of 18 matched" does not say *which* one did not.
    plan_problems = verify_plan()
    standalone_problems = verify_standalone()
    for problem in plan_problems:
        print(f"  PLAN MISMATCH: {problem}")
    for problem in standalone_problems:
        print(f"  STANDALONE MISMATCH: {problem}")

    if plan_problems or standalone_problems:
        raise SystemExit(
            "Nothing was written: fix the registry above until it matches the "
            "applied migrations, then re-run."
        )

    for name, (tables, previous) in PLAN.items():
        write(name, tables, previous)
        print(f"  {name}/{FILENAME} ({len(tables)} table(s))")

    # Every entry was compared byte-for-byte against the file it would rewrite
    # before a single byte was written, so reaching this line means the run
    # regenerated 18 files without changing any of them. The standalone count is
    # of migrations, not of apps: an app can have several.
    print(
        f"{len(PLAN)} RLS migration(s) written, all byte-identical to the "
        f"versions already applied; {len(standalone_entries())} standalone RLS "
        f"migration(s) checked"
    )
