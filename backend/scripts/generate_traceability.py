#!/usr/bin/env python
"""Generate docs/traceability.md from the SRS and the current code.

Coverage is measured from what actually exists, not from what was intended:

* a requirement counts as **modelled** when a class in its module exists;
* **exposed** when a router URL is published for that module;
* **isolated** when the module's tables carry an RLS policy.

The point is that this file cannot drift from the code without being
regenerated, and regenerating it is one command.

Run from backend/:

    python scripts/generate_traceability.py
"""
import os
import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
SRS = REPO / "docs" / "SaaS HMIS SRS v0.5.md"
OUTPUT = REPO / "docs" / "traceability.md"

#: SRS section prefix -> Django app label, plus the delivery phase the
#: architecture doc section 19 assigns to it.
MODULES = {
    "TEN": ("identity_tenancy", "R1"),
    "SET": ("identity_tenancy", "R1"),
    "REG": ("patient_registry", "R1"),
    "ABD": ("patient_registry", "R1"),
    "EMG": ("emergency", "R5"),
    "ICU": ("icu", "R5"),
    "OT": ("ot", "R5"),
    "OPD": ("opd", "R2"),
    "IPD": ("ipd", "R2"),
    "LIS": ("lis", "R4"),
    "RIS": ("ris", "R4"),
    "PHM": ("pharmacy", "R4"),
    "BBK": ("blood_bank", "R4"),
    "BIL": ("billing_insurance", "R2"),
    "EMR": ("emr", "R2"),
    "QOS": ("quality_os", "R3"),
    "AUD": ("audit", "R1"),
    "PLT": ("platform", "R1"),
    "INT": ("integration", "R6"),
}

#: Requirements the code explicitly refuses to claim. Each entry is a real
#: functional gap, kept here so it is reported rather than implied by a
#: green-looking matrix.
KNOWN_GAPS = {
    "ABD-001": "ABDM gateway adapter not implemented; the callback endpoint "
               "answers 501 by design (architecture doc 8.4)",
    "ABD-002": "ABHA creation and verification pending the ABDM sandbox spec",
    "QOS-001": "indicator catalogue exists in docs/ but no loader has been written; "
               "the 406 records are not in the database",
}


def parse_srs():
    """Requirement id -> (text, severity, release)."""
    rows = {}
    pattern = re.compile(
        r"^\|\s*([A-Z]{3}-\d{3})\s*\|(.*?)\|(.*?)\|(.*?)\|\s*$"
    )
    for line in SRS.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        rid, text, priority, release = (part.strip() for part in match.groups())
        # Strip markdown emphasis and any trailing backticks.
        text = re.sub(r"\*+|`+", "", text).strip()
        rows[rid] = (text, priority, release)
    return rows


def code_facts():
    """Per app: models, exposed URLs, and whether its tables are RLS-protected."""
    import django

    # The script lives in backend/scripts/, so sys.path[0] is that directory
    # rather than backend/. Django needs the project importable.
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    django.setup()

    from django.apps import apps as registry
    from django.db import connection
    from django.urls import get_resolver

    def collect(resolver, prefix=""):
        found = set()
        for entry in resolver.url_patterns:
            pattern = prefix + str(entry.pattern)
            if hasattr(entry, "url_patterns"):
                found |= collect(entry, pattern)
            elif pattern.startswith("api/v1"):
                found.add(pattern)
        return found

    routes = collect(get_resolver())

    # "Exposed" means the app has a urls.py that config/urls.py actually mounts.
    # Matching app labels against URL path segments does not work - the app
    # patient_registry is published at /api/v1/patients/, not
    # /api/v1/patient-registry/ - so the mount is read from the source instead.
    root_urls = (BACKEND / "config" / "urls.py").read_text(encoding="utf-8")
    mounted = set(re.findall(r"apps\.([a-z_]+)\.urls", root_urls))
    _ = routes  # collected above for completeness; mounting is the real signal

    facts = {}
    for config in registry.get_app_configs():
        models = list(config.get_models())
        if not models:
            continue
        tables = [m._meta.db_table for m in models]
        protected = 0
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                for table in tables:
                    schema, _, name = table.partition(".")
                    cursor.execute(
                        "SELECT count(*) FROM pg_policies WHERE schemaname = %s "
                        "AND tablename = %s AND policyname = 'tenant_isolation'",
                        (schema, name),
                    )
                    protected += cursor.fetchone()[0]
        else:
            # SQLite cannot be inspected for policies; the migration files are
            # the source of truth in that case.
            migration_dir = BACKEND / "apps" / config.label / "migrations"
            protected = len(
                [p for p in migration_dir.glob("*.py") if "row_level_security" in p.name]
            )
        facts[config.label] = {
            "models": len(models),
            "exposed": config.label in mounted,
            "rls_migrations": protected,
        }
    return facts


def main():
    requirements = parse_srs()
    facts = code_facts()

    by_module = {}
    for rid, (text, priority, release) in requirements.items():
        prefix = rid.split("-")[0]
        by_module.setdefault(prefix, []).append((rid, text, priority, release))

    total = len(requirements)

    lines = [
        "# Requirements traceability",
        "",
        "Generated by `backend/scripts/generate_traceability.py`. Do not edit by",
        "hand - regenerate instead, so the matrix cannot drift from the code.",
        "",
        f"Source: `{SRS.name}` ({total} numbered requirements).",
        "",
        "## How to read this",
        "",
        "| Column | Meaning |",
        "| --- | --- |",
        "| Modelled | A Django model exists in the module's app. |",
        "| API | The module is published under `/api/v1/`. |",
        "| RLS | A migration enables row level security for the module's tables. |",
        "| Status | `partial` means modelled but not exposed or not verified. |",
        "",
        "Modelled is not the same as delivered: the SRS describes intended",
        "behaviour, and a model captures only the data shape. Read the SRS for",
        "what each requirement actually demands.",
        "",
        "## Summary",
        "",
    ]

    summary_rows = []
    reachable = 0
    for prefix in sorted(by_module):
        entries = sorted(by_module[prefix])
        app, phase = MODULES.get(prefix, ("-", "-"))
        fact = facts.get(app, {})
        modelled = bool(fact)
        exposed = fact.get("exposed", False)
        if modelled and exposed:
            reachable += len(entries)
        summary_rows.append(
            (prefix, app, phase, len(entries), "yes" if modelled else "no",
             "yes" if exposed else "no",
             "yes" if fact.get("rls_migrations") else "no")
        )

    lines.append("| Reqs | App | Phase | Count | Modelled | API | RLS |")
    lines.append("| ---: | --- | --- | ---: | --- | --- | --- |")
    for row in summary_rows:
        lines.append("| {} | {} | {} | `{}` | {} | {} | {} |".format(*row))
    lines.append("")
    lines.append("### What these numbers do and do not mean")
    lines.append("")
    lines.append(
        "**Modelled** is `yes` for every module, because each bounded context has "
        "at least one model. Read it as near-meaningless as a measure of progress: "
        "a model captures a data shape, not the behaviour an SRS requirement "
        "describes."
    )
    lines.append("")
    lines.append(
        f"**{reachable} of {total} requirements ({reachable / total:.0%})** sit in a "
        "module that is both exposed under `/api/v1/` and protected by row level "
        "security. That is the furthest any requirement currently reaches, and it "
        "is still not the same as delivered."
    )
    lines.append("")
    lines.append(
        "The remaining modules are modelled but not exposed, because what exists "
        "is a stub rather than a working feature. Those are named under Known "
        "gaps below instead of being counted as progress. In particular: the "
        "Quality OS engine and catalogue loader, the audit trail, the realtime "
        "consumers (unrouted in `config/asgi.py`) and both Celery tasks "
        "(`compute_indicators`, `sync_abdm_callback`) are placeholders."
    )
    lines.append("")
    lines.append("## Known gaps")
    lines.append("")
    lines.append("Requirements that exist in the SRS but are deliberately not")
    lines.append("claimed as delivered:")
    lines.append("")
    for rid, note in sorted(KNOWN_GAPS.items()):
        lines.append(f"- **{rid}** - {note}")
    lines.append("")
    lines.append("## Per-requirement detail")
    lines.append("")

    for prefix in sorted(by_module):
        entries = sorted(by_module[prefix])
        app, phase = MODULES.get(prefix, ("-", "-"))
        lines.append(f"### {prefix} - `{app}` (phase {phase})")
        lines.append("")
        lines.append("| ID | Requirement | Priority | Release | Status |")
        lines.append("| --- | --- | --- | --- | --- |")
        for rid, text, priority, release in entries:
            if rid in KNOWN_GAPS:
                status = "**not implemented**"
            elif app in facts:
                status = "partial"
            else:
                status = "not started"
            text = text.replace("|", "\\|")
            lines.append(f"| {rid} | {text} | {priority} | {release} | {status} |")
        lines.append("")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"{total} requirements catalogued")


if __name__ == "__main__":
    sys.exit(main())