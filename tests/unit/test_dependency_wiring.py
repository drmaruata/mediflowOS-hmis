"""Every declared dependency should be either used or explicitly accounted for.

AGENTS.md requires that unused dependencies be flagged rather than silently
relied on, and that requirements.txt and pyproject.toml stay synchronized. Both
are easy to violate over time and invisible at runtime, so they are checked here.

The mapping from distribution name to import name is not automatable in general
(``django-cors-headers`` is ``corsheaders``; ``psycopg[binary]`` is ``psycopg``),
so it is spelled out below rather than guessed. The point is not to prove the
mapping is complete - it is to make any package that stops being used show up as
a test failure instead of a surprise in an audit.
"""
import pathlib
import re
import tomllib

import pytest

pytestmark = pytest.mark.unit

BACKEND = pathlib.Path(__file__).resolve().parent.parent.parent / "backend"

#: distribution -> module actually imported by the source. Covers the packages
#: that are expected to be used today; UNIMPLEMENTED names map to the module
#: that will be imported once the feature lands.
IMPORT_NAME = {
    "Django": "django",
    "djangorestframework": "rest_framework",
    "django-cors-headers": "corsheaders",
    "djangorestframework-simplejwt": "rest_framework_simplejwt",
    "django-otp": "django_otp",
    "drf-spectacular": "drf_spectacular",
    "psycopg": "psycopg",
    "redis": "redis",
    "celery": "celery",
    "django-celery-beat": "django_celery_beat",
    "channels": "channels",
    "channels-redis": "channels_redis",
    "daphne": "daphne",
    "Pillow": "PIL",
    "openpyxl": "openpyxl",
    "reportlab": "reportlab",
    "httpx": "httpx",
    "opentelemetry-sdk": "opentelemetry",
    "opentelemetry-instrumentation-django": "opentelemetry",
    "sentry-sdk": "sentry_sdk",
}

#: Declared, deliberately never imported, because the distribution is pulled in
#: indirectly by Django or Celery rather than by this project's source.
NOT_IMPORTED = {
    "daphne": "runs as the ASGI server process; never imported by name",
    "psycopg": "imported by Django's PostgreSQL backend, not by this project's source",
    "redis": "imported by Celery's broker transport, not by this project's source",
}

#: Declared for documented features that are not implemented yet. The import name
#: is recorded so the staleness check can tell when one starts being used.
UNIMPLEMENTED = {
    "Pillow": "printable facility/counter QR codes (architecture doc 8.4)",
    "openpyxl": "Quality OS regulatory exports (9.9)",
    "reportlab": "Quality OS regulatory exports (9.9)",
    "httpx": "ABDM gateway, HL7 v2 bridge and payer adapters (12)",
}


def _requirement_names() -> list[str]:
    names = []
    for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        names.append(re.split(r"[<>=!\[; ]", line, maxsplit=1)[0].strip())
    return names


def _pyproject_dependencies() -> list[str]:
    data = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    return [
        re.split(r"[<>=!\[]", entry, maxsplit=1)[0].strip()
        for entry in data["project"]["dependencies"]
    ]


def _referenced_modules() -> set[str]:
    """Module names referenced anywhere in the backend source.

    Settings reference modules as strings (``"rest_framework"``,
    ``"django_otp.plugins.otp_totp"``) rather than importing them, so a scan of
    import statements alone would report most of the stack as unused.
    """
    found = set()
    for root in ("apps", "common", "config", "workers"):
        for path in (BACKEND / root).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(
                r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", text, re.M
            ):
                found.add(match.group(1).split(".")[0])
            for match in re.finditer(r"[\"']([A-Za-z_][\w.]*)[\"']", text):
                found.add(match.group(1).split(".")[0])
    return found


def test_requirements_and_pyproject_are_synchronized():
    """AGENTS.md requires both files to carry the same constraints."""
    assert sorted(_requirement_names()) == sorted(_pyproject_dependencies()), (
        "requirements.txt and pyproject.toml list different dependencies; "
        "AGENTS.md requires them to be edited together"
    )


@pytest.mark.parametrize("name", _requirement_names())
def test_declared_dependency_is_accounted_for(name):
    """Each dependency must be imported, run as a process, or declared pending."""
    if name in NOT_IMPORTED or name in UNIMPLEMENTED:
        return

    module = IMPORT_NAME.get(name)
    if module is None:
        # A package added without a mapping entry. Asserting the mapping stays
        # exhaustive is the point: an unmapped package has not been reviewed.
        pytest.fail(
            f"{name} is declared but has no entry in IMPORT_NAME. Add its import "
            "name, or move it to NOT_IMPORTED / UNIMPLEMENTED if it is not used "
            "yet."
        )

    if module in _referenced_modules():
        return

    pytest.fail(
        f"{name} is declared but {module!r} appears nowhere in the backend "
        "source. Remove it, or add it to UNIMPLEMENTED with the requirement it "
        f"serves so the gap stays visible. See {__file__}."
    )


def test_unimplemented_ledger_is_not_stale():
    """An entry should disappear once its module is actually referenced."""
    referenced = _referenced_modules()
    stale = {
        name
        for name in UNIMPLEMENTED
        if IMPORT_NAME.get(name, name) in referenced
    }

    assert not stale, (
        f"{sorted(stale)} are listed as unimplemented but are now referenced. "
        "Remove them from UNIMPLEMENTED so the ledger stays truthful."
    )


def test_import_name_map_has_no_stale_entries():
    """A dependency that was removed should not linger in the map."""
    declared = set(_requirement_names())

    assert set(IMPORT_NAME) <= declared, (
        f"{sorted(set(IMPORT_NAME) - declared)} are mapped but no longer declared"
    )