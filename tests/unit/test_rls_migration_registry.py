"""The RLS registry accounts for every migration that enables a policy.

``scripts/add_rls_migrations.py`` is the only place that records *where* each
tenant-owned table's row level security lives: PLAN for the per-app ``0004``
migrations it generates, STANDALONE for the ones that cannot be folded into a
``0004`` because the table was created later, and UNPROTECTED_TABLES for the
tenant-owned table whose absence of a policy is deliberate.

RLS is DDL with no model state, so none of this is visible to
``makemigrations --check``, to the ORM, or to any review of a diff that adds a
migration. A table can gain RLS without the registry naming it and every test
still passes - which is exactly what happened: six tables across three apps had
a policy attached in their own migration and appeared nowhere in the registry,
so the document claiming to be the answer to "is this table protected, and
where?" answered nothing for them.

These cases are therefore about the registry's own coverage, not about any one
table's policy.
"""
from importlib import import_module
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"

#: Unit: pure registry metadata, no database and no migration is applied.
pytestmark = pytest.mark.unit


def _script():
    return import_module("scripts.add_rls_migrations")


def _rls_migration_files() -> set[tuple[str, str]]:
    """Every ``(module, filename)`` migration that calls ``rls.enable``.

    Discovered from the files rather than from the registry, so the registry is
    checked against the migrations themselves. A registry that agreed only with
    itself would pass a comparison against itself.
    """
    found = set()
    for module_dir in sorted((BACKEND / "apps").iterdir()):
        migrations = module_dir / "migrations"
        if not migrations.is_dir():
            continue
        for path in sorted(migrations.glob("0*.py")):
            if "rls.enable" in path.read_text(encoding="utf-8"):
                found.add((module_dir.name, path.name))
    return found


def _registered() -> dict[tuple[str, str], str]:
    """Every registered migration as ``(module, filename) -> reason it is not a 0004``.

    PLAN's entries all map to the same generated filename, so the value is empty
    for them and the entry's ``previous`` for the rest.
    """
    script = _script()
    registered = {
        (module, script.FILENAME): "" for module in script.PLAN
    }
    for module, entry in script.standalone_entries():
        registered[(module, entry.filename)] = entry.previous
    return registered


class TestCoverage:
    def test_every_migration_that_enables_rls_is_registered(self):
        """The gap this file exists for: a migration no registry entry names.

        Six tenant tables were protected by migrations the registry did not
        mention - ``identity.setup_progress``, ``identity.reference_data``,
        ``identity.baseline_input``, ``identity.config_revision``,
        ``opd.token_series`` and ``registry.sequence`` - so the answer the
        registry gave for each of them was nothing at all.

        A seventh turned up when this was written: ``identity_tenancy``'s
        ``0006_enable_rls_identity_roles``, which protects three more tables and
        was registered nowhere either. Enumerating the migrations and asking
        what each one names is what found it; reading the registry and counting
        would not have.
        """
        registered = set(_registered())

        unregistered = sorted(_rls_migration_files() - registered)

        assert unregistered == []

    def test_the_registry_names_nothing_that_does_not_exist(self):
        """The other direction: an entry with no migration protects nothing.

        A registry entry for a file nobody wrote is a claim with nothing behind
        it, and it is the failure that reads as coverage - so the two sets are
        asserted equal, not merely "no unregistered".
        """
        registered = set(_registered())

        assert sorted(_rls_migration_files()) == sorted(registered)

    def test_plan_and_standalone_name_no_table_twice(self):
        """The two registries are disjoint, and none is lost.

        A table in both means a generated ``0004`` and a standalone migration
        racing to enable the same policy, with the rewritten history the whole
        split exists to prevent.
        """
        script = _script()
        plan_listed = [table for tables, _ in script.PLAN.values() for table in tables]
        standalone = set(script.standalone_tables())
        plan_tables = set(plan_listed)

        assert plan_tables & standalone == set()
        # No duplicates within PLAN either: a table listed twice there is
        # rewritten into two DDL statements for one policy, silently.
        assert len(plan_listed) == len(plan_tables)
        # Sanity on the shape of the answer, so an emptied registry cannot pass
        # a disjointness assertion by being empty.
        assert len(plan_tables) == 46
        assert len(standalone) == 11

    def test_a_table_with_no_policy_is_recorded_as_deliberate(self):
        """``platform.scheduled_job`` is unprotected on purpose, and says so.

        It is tenant-owned, so "absent from PLAN and STANDALONE" is otherwise
        indistinguishable from "nobody got round to it" - which is how the six
        unregistered tables stayed invisible. The record points at
        ``apps/workers/tasks.py``'s ``run_scheduled_job`` docstring, which is
        where the scoping argument lives. Adding a policy there is a deliberate
        decision with its own migration, not something a registry entry may do.
        """
        script = _script()
        reason = script.UNPROTECTED_TABLES["platform.scheduled_job"]

        # Not claimed by either registry, and the reason is a reference, not a
        # policy: nothing in this script emits DDL for an unprotected table.
        assert "platform.scheduled_job" not in script.standalone_tables()
        assert "platform.scheduled_job" not in {
            table for tables, _ in script.PLAN.values() for table in tables
        }
        assert "tasks.py" in reason

    def test_the_accounting_is_complete_for_platform(self):
        """The app this task added a table to: two tenant tables, one protected.

        ``platform.file`` arrived with its own ``0006`` because ``0004`` was
        already applied; ``platform.scheduled_job`` arrived in the same
        migration and is the deliberate gap. Both answers have to be findable in
        this one file, which is the smallest version of the question the full
        registry answers.
        """
        script = _script()

        assert script.standalone_tables()["platform.file"][1].filename == (
            "0006_enable_row_level_security.py"
        )
        assert "platform.scheduled_job" in script.UNPROTECTED_TABLES
        assert "platform.scheduled_job" not in script.standalone_tables()


class TestVerification:
    """``verify_standalone`` is the checker the run gates on, so it is pinned.

    Falsified through the public function rather than by reading its source, so
    a future edit cannot drop a check and leave this green.
    """

    def test_the_registered_entries_verify_clean(self, monkeypatch):
        script = _script()
        # ``verify_standalone`` reads the module global through
        # ``standalone_entries``; restored by the fixture either way.
        monkeypatch.setattr(script, "STANDALONE", dict(script.STANDALONE))

        assert script.verify_standalone() == ()

    def test_verify_standalone_checks_the_recorded_previous(self, monkeypatch):
        """A wrong ``previous`` is reported, not silently accepted.

        ``verify_plan`` has always compared the dependency it records against
        the migration's real ``dependencies``; ``verify_standalone`` compared
        only ``TABLES``, so an entry could claim an ordering the applied
        migrations do not have. For the shape where RLS runs in the same
        ``RunPython`` that creates the table, that means a policy attached
        before the table exists: a failure on PostgreSQL, and a silent no-op on
        the SQLite the fast suite runs on.
        """
        script = _script()
        module = "identity_tenancy"
        entry = script.STANDALONE[module][0]
        drifted = script.StandaloneEntry(
            filename=entry.filename,
            previous="0001_initial",
            tables=entry.tables,
            # Everything else is carried over, so the only thing wrong with the
            # entry is its recorded predecessor and the single problem below is
            # attributable to it.
            declarations=entry.declarations,
            additional_previous=entry.additional_previous,
        )
        # Only the first entry is falsified, so the problem reported is
        # attributable to the dependency rather than to the rest of the module.
        monkeypatch.setattr(
            script, "STANDALONE", {module: (drifted, *script.STANDALONE[module][1:])}
        )

        problems = script.verify_standalone()

        assert len(problems) == 1
        assert problems[0].startswith(f"{module}/{entry.filename}: depends on")
        assert "0001_initial" in problems[0]

    def test_verify_standalone_reports_a_missing_file(self, monkeypatch):
        """A registry entry whose migration is gone is a gap, not a pass.

        The entry would otherwise keep answering "this table is protected" for a
        table with no policy, which is the one thing the registry must never do.
        """
        script = _script()
        monkeypatch.setattr(
            script,
            "STANDALONE",
            {
                "platform": (
                    script.StandaloneEntry(
                        filename="9999_never_written.py",
                        previous="0006_enable_row_level_security",
                        tables=("platform.file",),
                    ),
                ),
            },
        )

        assert script.verify_standalone() == (
            "platform/9999_never_written.py: missing",
        )

    def test_verify_standalone_reports_a_table_list_that_drifted(self, monkeypatch):
        """The table list is still checked, alongside the new dependency check.

        Adding a check must not have displaced the one that was there: an entry
        naming a table its migration does not protect is the original drift this
        registry exists to catch.
        """
        script = _script()
        entry = script.STANDALONE["platform"][0]
        monkeypatch.setattr(
            script,
            "STANDALONE",
            {
                "platform": (
                    script.StandaloneEntry(
                        filename=entry.filename,
                        previous=entry.previous,
                        tables=("platform.scheduled_job",),
                    ),
                ),
            },
        )

        problems = script.verify_standalone()

        assert len(problems) == 1
        assert problems[0].startswith(f"platform/{entry.filename}: declares")
        assert "platform.scheduled_job" in problems[0]