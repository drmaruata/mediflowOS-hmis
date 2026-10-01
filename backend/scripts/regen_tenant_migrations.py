#!/usr/bin/env python
"""Regenerate the step-5 tenant_id migrations end to end.

Run from backend/ whenever the tenancy model changes:

    python scripts/regen_tenant_migrations.py

The sequence matters and is not a convenience:

1. makemigrations refuses to add a NOT NULL column without a default, and the
   only defensible default would be a guess at which tenant owns each existing
   row. So the fields are temporarily marked nullable to obtain an *expand*
   migration.
2. The backfill RunPython is injected into that migration, declaring the
   cross-app dependencies the raw SQL needs.
3. The fields are restored to NOT NULL, and makemigrations produces the
   *contract* migration that tightens them.

The temporary edits only ever touch the 20 models listed in make_nullable.py.
"""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def run(*args: str) -> None:
    result = subprocess.run(
        [PYTHON, *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"command failed: {' '.join(args)}\n{result.stdout}\n{result.stderr}")
    print(f"  {' '.join(args[:2])} ... ok")


def clear_generated() -> None:
    removed = 0
    for path in (BACKEND / "apps").rglob("migrations/000[23]_*.py"):
        path.unlink()
        removed += 1
    if removed:
        print(f"  removed {removed} previously generated 0002/0003 migration(s)")


def main() -> None:
    print("regenerating step-5 tenant_id migrations")
    clear_generated()
    run("scripts/make_nullable.py", "on")
    run("manage.py", "makemigrations", "--settings=config.settings.test")
    run("scripts/make_nullable.py", "off")
    run("scripts/add_backfill.py")
    run("manage.py", "makemigrations", "--noinput", "--settings=config.settings.test")
    print("done")


if __name__ == "__main__":
    main()