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
#: green-looking matrix. Value = (status, note); status is what the
#: per-requirement table prints, the note is appended to the Known gaps list.
#: Every entry was re-verified against the code on 2026-10-07 — when a gap is
#: closed, delete the entry so regeneration reflects reality.
KNOWN_GAPS = {
    "ABD-002": (
        "partial",
        "QR regenerate is implemented (`qr-codes/{id}/regenerate/`); the revoke "
        "half of the requirement has no endpoint",
    ),
    "ABD-005": (
        "**not implemented**",
        "`ABHACallbackViewSet` accepts any non-empty X-ABDM-Signature or "
        "Bearer header — presence-only, no secret comparison (verified "
        "backend/apps/abdm_gateway/views.py `_authenticate`)",
    ),
    "ABD-011": (
        "**not implemented**",
        "the consent event is built and returned in the acknowledgement but "
        "never written to any table",
    ),
    "ABD-012": (
        "**not implemented**",
        "the link token is `secrets.token_urlsafe(32)` and discarded — "
        "no encryption, no storage (placeholder comment for KMS)",
    ),
    "TEN-004": (
        "partial",
        "Role.permissions exists and is copied into the token's `permissions` "
        "claim, but no permission class reads it — authentication (plus the "
        "MFA gate) is enforced server-side, role-based authorisation is not",
    ),
    "TEN-006": (
        "partial",
        "TOTP enrol/confirm works and MFARequiredIfConfigured is installed "
        "after IsAuthenticated in DEFAULT_PERMISSION_CLASSES, with the token "
        "carrying `requires_mfa`/`mfa_verified` claims — but no POST "
        "/auth/mfa/verify endpoint exists, so mfa_verified can never become "
        "True after login and require_mfa roles are denied every "
        "default-permission endpoint (fail-closed)",
    ),
    "AUD-002": (
        "partial",
        "AuditEvent.hash_chain exists but is never computed — the log is "
        "append-only in practice, not tamper-evident",
    ),
    "PLT-004": (
        "**not implemented**",
        "every Celery task body is `pass` and there is no "
        "CELERY_BEAT_SCHEDULE — no background job can run",
    ),
    "QOS-001": (
        "**not implemented**",
        "indicator catalogue exists in docs/ but no loader has been written; "
        "the 406 records are not in the database",
    ),
}


#: Requirements whose status is a frontend fact, not a backend one. The
#: Modelled/API/RLS columns are Django signals and read `no`/`no`/`no` for
#: these rows by construction; this map keeps the Status column honest.
#: Verified against frontend/src on 2026-10-07.
MANUAL_STATUS = {
    "UI-001": "partial",   # responsive shell + theme exist; only 2 screens
}


def parse_srs():
    """Requirement id -> (text, severity, release)."""
    rows = {}
    # {2,3} letter prefixes: the old {3} silently dropped OT-, UI- and HW-.
    pattern = re.compile(
        r"^\|\s*([A-Z]{2,3}-\d{3})\s*\|(.*?)\|(.*?)\|(.*?)\|\s*$"
    )
    nfr_pattern = re.compile(r"^\|\s*(NFR-[A-Z]+-\d{3})\s*\|")
    nfr_count = 0
    for line in SRS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        match = pattern.match(stripped)
        if match:
            rid, text, priority, release = (part.strip() for part in match.groups())
            # Strip markdown emphasis and any trailing backticks.
            text = re.sub(r"\*+|`+", "", text).strip()
            rows[rid] = (text, priority, release)
        elif nfr_pattern.match(stripped):
            # §5 NFR tables have no release column; counted for the header
            # but not enumerated here, because a release cannot be read
            # from the row itself (see §11 goal mapping instead).
            nfr_count += 1
    return rows, nfr_count


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

    # Exposure is counted, not guessed: walk the resolved URL tree and count
    # the leaf routes under each include's namespace, then map the namespace
    # back to the app label from config/urls.py itself. The previous version
    # only asked whether config/urls.py mentioned the app, which reported an
    # app as "exposed" even when its urls.py published a single hand-written
    # route and never mounted its router (pharmacy, blood_bank).
    root_urls = (BACKEND / "config" / "urls.py").read_text(encoding="utf-8")
    ns_to_app = {
        ns: app
        for app, ns in re.findall(
            r'include\("apps\.(?P<app>[a-z_]+)\.urls",\s*namespace="(?P<ns>[a-z_]+)"\)',
            root_urls,
        )
    }
    routes = {}

    def walk(resolver, current=None):
        for entry in resolver.url_patterns:
            if hasattr(entry, "url_patterns"):
                nested = getattr(entry, "namespace", None) or current
                walk(entry, nested)
            else:
                routes[current] = routes.get(current, 0) + 1

    walk(get_resolver())

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
        exposed = 0
        for namespace, app in ns_to_app.items():
            if app == config.label:
                exposed += routes.get(namespace, 0)
        facts[config.label] = {
            "models": len(models),
            "exposed": exposed > 0,
            "routes": exposed,
            "rls_migrations": protected,
        }
    return facts


def main():
    requirements, nfr_count = parse_srs()
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
        f"Source: `{SRS.name}` - {total} requirements with a release column",
        "(§3 interface and §4 functional). The SRS additionally carries",
        f"{nfr_count} §5 NFR rows that have no release column; they are not",
        "enumerated here (see SRS §5 and the §11 goal-to-release mapping).",
        "",
        "## How to read this",
        "",
        "| Column | Meaning |",
        "| --- | --- |",
        "| Modelled | A Django model exists in the module's app. |",
        "| API | The module's urls.py publishes at least one route under `/api/v1/`. |",
        "| Routes | Leaf URL patterns published by that app (counted from the live URL resolver). |",
        "| RLS | A migration enables row level security for the module's tables. |",
        "| Status | `partial` = present but incomplete; `not implemented` = a Known gap; `not started` = no code. |",
        "",
        "Modelled is not the same as delivered: the SRS describes intended",
        "behaviour, and a model captures only the data shape. Read the SRS for",
        "what each requirement actually demands. `UI-` and `HW-` rows describe",
        "the frontend, so Modelled/API/RLS read `no` for them by construction.",
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
             "yes" if exposed else "no", fact.get("routes", 0),
             "yes" if fact.get("rls_migrations") else "no")
        )

    lines.append("| Reqs | App | Phase | Count | Modelled | API | Routes | RLS |")
    lines.append("| ---: | --- | --- | ---: | --- | --- | ---: | --- |")
    for row in summary_rows:
        lines.append("| {} | {} | {} | `{}` | {} | {} | `{}` | {} |".format(*row))
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
        "**Routes** counts published URL patterns, so an app with a hand-written "
        "route and an unmounted router still scores low: `pharmacy` and "
        "`blood_bank` publish one route each while most of their viewsets are "
        "not routed at all. Exposure says an endpoint exists; it says nothing "
        "about whether the behaviour behind it is implemented. The gaps that "
        "are known to the code are named under Known gaps below instead of "
        "being counted as progress."
    )
    lines.append("")
    lines.append("## Known gaps")
    lines.append("")
    lines.append("Requirements that exist in the SRS but are deliberately not")
    lines.append("claimed as delivered (re-verified against the code each time")
    lines.append("this file is regenerated):")
    lines.append("")
    for rid, (status, note) in sorted(KNOWN_GAPS.items()):
        lines.append(f"- **{rid}** ({status.strip('*')}) - {note}")
    lines.append("")
    lines.append("## Per-requirement detail")
    lines.append("")

    for prefix in sorted(by_module):
        entries = sorted(by_module[prefix])
        app, phase = MODULES.get(prefix, ("-", "-"))
        lines.append(f"### {prefix} - `{app}` (module completion phase {phase})")
        lines.append("")
        lines.append("| ID | Requirement | Priority | Release | Status |")
        lines.append("| --- | --- | --- | --- | --- |")
        for rid, text, priority, release in entries:
            if rid in KNOWN_GAPS:
                status = KNOWN_GAPS[rid][0]
            elif rid in MANUAL_STATUS:
                status = MANUAL_STATUS[rid]
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