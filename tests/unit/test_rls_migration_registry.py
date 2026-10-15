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

#: The migration whose registration the falsification cases remove. Named once
#: so the test that drops it and the test that counts it cannot drift apart.
DROPPED = "0007_featureflag.py"


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

    def test_dropping_a_registry_entry_is_reported(self, monkeypatch):
        """The coverage check above, falsified: remove an entry, and it bites.

        The check reads the migrations from disk and the registry from the
        module, so removing one entry is exactly the drift it exists to catch -
        and this is the drift that matters most for ``0007``, whose whole purpose
        is to re-attach a policy nothing else will re-attach. A registry that
        had lost the entry would still answer "where is this table protected"
        with 0004, which no longer protects it.
        """
        script = _script()
        monkeypatch.setattr(
            script,
            "STANDALONE",
            {
                module: tuple(
                    entry for entry in entries if entry.filename != DROPPED
                )
                or ()
                for module, entries in script.STANDALONE.items()
            },
        )

        registered = set(_registered())
        unregistered = sorted(_rls_migration_files() - registered)

        assert unregistered == [("platform", DROPPED)]

    def test_the_registry_names_nothing_that_does_not_exist(self):
        """The other direction: an entry with no migration protects nothing.

        A registry entry for a file nobody wrote is a claim with nothing behind
        it, and it is the failure that reads as coverage - so the two sets are
        asserted equal, not merely "no unregistered".
        """
        registered = set(_registered())

        assert sorted(_rls_migration_files()) == sorted(registered)

    def test_plan_and_standalone_overlap_only_where_a_reapplication_is_recorded(self):
        """The disjointness rule, restated so this registry can still satisfy it.

        The rule was "the two registries name no table twice", because a table in
        both means a generated ``0004`` and a standalone migration racing to
        enable the same policy. That stopped being satisfiable when
        ``platform.feature_flag`` was re-created: ``0004`` had written that
        table's policy, ``0005`` dropped the table with it, and ``0007`` has to
        attach a policy again - so the table is genuinely named twice and one of
        the two names is a *record of history*, not a second writer.

        So the rule is narrowed rather than deleted, and each half is still
        falsifiable. Every overlap is declared through ``reapplies`` (an overlap
        nobody declared is the original race); no table is duplicated *within*
        PLAN, which would be rewritten into two DDL statements for one policy,
        silently; and no table is re-applied twice. The shape assertion at the
        end keeps an emptied registry from passing a disjointness claim by being
        empty.
        """
        script = _script()
        plan_listed = [table for tables, _ in script.PLAN.values() for table in tables]
        plan_written = set(plan_listed)
        standalone_written = set(script.standalone_tables())
        reapplied = set(script.reapplied_tables())

        assert plan_written & standalone_written == reapplied
        assert reapplied == {"platform.feature_flag"}
        # No duplicates within PLAN: a table listed twice there is rewritten
        # into two DDL statements for one policy, silently.
        assert len(plan_listed) == len(plan_written)
        assert len(standalone_written) == 12
        # Sanity on the shape of the answer, so an emptied registry cannot pass a
        # disjointness assertion by being empty.
        assert len(plan_written) == 46

    def test_every_reapplication_is_recorded_and_ordered(self, monkeypatch):
        """The three claims that replaced disjointness, verified clean.

        Run through the public function rather than by reading its source, so a
        future edit cannot drop one of the checks and leave this green - and the
        three falsification cases below drop each one in turn to show they bite.
        """
        script = _script()
        monkeypatch.setattr(script, "STANDALONE", dict(script.STANDALONE))

        assert script.verify_reapplied() == ()

    def test_an_undeclared_overlap_is_reported(self, monkeypatch):
        """A second writer for a PLAN table is the original race, and it fails.

        The entry is the *correct* one in every other respect - right filename,
        right dependency, right table list - so only the missing ``reapplies``
        declaration distinguishes it, which is exactly the claim under test.
        """
        script = _script()
        entry = next(e for e in script.STANDALONE["platform"] if e.reapplies)
        undeclared = script.StandaloneEntry(
            filename=entry.filename,
            previous=entry.previous,
            tables=entry.tables,
        )
        others = tuple(e for e in script.STANDALONE["platform"] if e is not entry)
        monkeypatch.setattr(script, "STANDALONE", {"platform": (undeclared, *others)})

        problems = script.verify_reapplied()

        assert problems == (
            "platform.feature_flag: named by both PLAN and STANDALONE but not "
            "recorded as re-applied",
        )

    def test_a_reapplication_of_a_table_no_plan_entry_wrote_is_reported(
        self, monkeypatch
    ):
        """Claiming to restore a policy that never existed is a failure too.

        The re-application is recorded, and nothing else is wrong with it - which
        is the point. A stale entry left behind after a table was dropped for
        good would otherwise keep answering "this table is protected" for a
        table the registry cannot point at.
        """
        script = _script()
        entry = next(e for e in script.STANDALONE["platform"] if e.reapplies)
        invented = script.StandaloneEntry(
            filename=entry.filename,
            previous=entry.previous,
            tables=("platform.never_existed",),
            reapplies=("platform.never_existed",),
        )
        # Added rather than swapped in, so the one legitimate re-application
        # stays recorded and the single problem reported is attributable to the
        # invented one.
        monkeypatch.setattr(
            script,
            "STANDALONE",
            {"platform": (invented, *script.STANDALONE["platform"])},
        )

        problems = script.verify_reapplied()

        assert problems == (
            "platform.never_existed: recorded as re-applied but not named by any "
            "PLAN entry",
        )

    def test_a_reapplication_that_runs_before_the_policy_it_restores_is_reported(
        self, monkeypatch
    ):
        """The ordering claim, read from the migration graph rather than asserted.

        ``0007`` is three migrations downstream of ``0004``, so the recorded
        ``previous`` alone does not prove the ordering - the dependency graph
        does. Falsified by registering the re-application against ``0001``, which
        is a real migration that genuinely precedes ``0004`` (it creates the
        table, with no policy): on PostgreSQL the policy would then be attached
        before the one it claims to restore, and on the SQLite the fast suite runs
        on the whole thing would be a silent no-op.
        """
        script = _script()
        entry = next(e for e in script.STANDALONE["platform"] if e.reapplies)
        early = script.StandaloneEntry(
            filename="0001_initial.py",
            previous="0001_initial",
            tables=entry.tables,
            reapplies=entry.reapplies,
        )
        monkeypatch.setattr(
            script,
            "STANDALONE",
            {"platform": (early, *(e for e in script.STANDALONE["platform"] if e is not entry))},
        )

        problems = script.verify_reapplied()

        assert problems == (
            "platform/0001_initial.py: re-applies platform.feature_flag, which "
            "PLAN protects in platform/0004_enable_row_level_security.py - that "
            "migration does not run first",
        )

    def test_a_cross_app_reapplication_is_checked_against_the_writing_app(
        self, monkeypatch
    ):
        """Claim 3 reads the PLAN entry's app, not the re-applying entry's module.

        The two are the same app for every legitimate entry - a ``DeleteModel``
        only drops a table in the app that owns the model - which is exactly what
        hid the defect. With the app taken from the entry itself, a re-application
        registered against *another* app's table was compared against that other
        app's own ``0004``, a migration it does run after, and reported clean:
        a check that passes for the wrong reason.

        Built from two real migrations so the difference is the real graph rather
        than a stub. ``abdm_gateway/0005_abhacallbacklog_link_token_enc_consentevent``
        really does depend on ``abdm_gateway/0004_enable_row_level_security``, so
        the entry's-own-app reading is satisfied; ``platform``'s graph does not
        contain that filename at all, so the app that really wrote the policy -
        ``platform``, whose PLAN entry names ``platform.feature_flag`` - has no
        edge to it. The shape cannot be legitimate: the drop and the re-add of a
        table cannot be in different apps, and nothing in the suite can establish
        an ordering across two migration graphs.
        """
        script = _script()
        entry = next(e for e in script.STANDALONE["platform"] if e.reapplies)
        # The real platform entry is swapped out, because ``standalone_tables``
        # refuses to register one table twice - which is itself the guarantee
        # that keeps the re-application single.
        monkeypatch.setattr(
            script,
            "STANDALONE",
            {
                **script.STANDALONE,
                "platform": tuple(
                    e for e in script.STANDALONE["platform"] if e is not entry
                ),
                "abdm_gateway": (
                    *script.STANDALONE["abdm_gateway"],
                    script.StandaloneEntry(
                        filename=(
                            "0005_abhacallbacklog_link_token_enc_consentevent.py"
                        ),
                        previous=script.FILENAME,
                        tables=entry.tables,
                        reapplies=entry.reapplies,
                    ),
                ),
            },
        )

        problems = script.verify_reapplied()

        assert problems == (
            "abdm_gateway/0005_abhacallbacklog_link_token_enc_consentevent.py: "
            "re-applies platform.feature_flag, which PLAN protects in "
            "platform/0004_enable_row_level_security.py - that migration does "
            "not run first",
        )

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
        """The app every shape in this registry appeared in: all answers findable.

        ``platform.file`` arrived with its own ``0006`` because ``0004`` was
        already applied; ``platform.feature_flag`` was dropped by ``0005`` and
        re-added by ``0007``, which has to re-attach the policy as well; and
        ``platform.scheduled_job`` arrived in the same migration and is the
        deliberate gap. Three shapes - a new table, a re-added table, an
        unprotected one - and all three answers have to be findable in this one
        file, which is the smallest version of the question the full registry
        answers.
        """
        script = _script()

        assert script.standalone_tables()["platform.file"][1].filename == (
            "0006_enable_row_level_security.py"
        )
        reapply = script.standalone_tables()["platform.feature_flag"][1]
        assert reapply.filename == "0007_featureflag.py"
        assert reapply.reapplies == ("platform.feature_flag",)
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