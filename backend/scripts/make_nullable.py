"""Temporarily mark the step-5 tenant_id additions nullable so the autodetector
can emit an expand migration. Reverted by the caller after makemigrations.

Not part of the application. Deleted once the migrations are generated.
"""
import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parent.parent / "apps"

# (module, model) pairs that gained tenant_id in step 5. Every other tenant_id
# already existed in 0001_initial and must not be touched.
NEW_TENANT_ID = {
    "identity_tenancy": ["Ward", "Bed", "ServiceUnit", "StaffPosition"],
    "patient_registry": ["IntakePoint", "QRCode"],
    "opd": ["OPDEncounter"],
    "ipd": ["BedStatus"],
    "icu": ["Device"],
    "ot": ["SurgeryRecord"],
    "lis": ["LabResult"],
    "pharmacy": ["StockBatch", "Dispense"],
    "blood_bank": ["Donation", "CrossMatch", "TransfusionReaction"],
    "billing_insurance": ["Payment", "Claim"],
    "emr": ["ProblemList"],
    "integration": ["IntegrationAdapter"],
}

FIELD = "tenant_id = models.UUIDField(db_index=True)"
NULLABLE = "tenant_id = models.UUIDField(db_index=True, null=True)"


def toggle(apps_dir: pathlib.Path, make_nullable: bool) -> int:
    changed = 0
    for module, models in NEW_TENANT_ID.items():
        path = apps_dir / module / "models.py"
        source = path.read_text(encoding="utf-8")
        pieces = re.split(r"(?m)^(?=class )", source)

        for model in models:
            for index, chunk in enumerate(pieces):
                if not chunk.startswith(f"class {model}("):
                    continue
                target, replacement = (
                    (FIELD, NULLABLE) if make_nullable else (NULLABLE, FIELD)
                )
                if target not in chunk:
                    sys.exit(f"{module}.{model}: expected {target!r} not found")
                pieces[index] = chunk.replace(target, replacement, 1)
                changed += 1
                break
            else:
                sys.exit(f"{module}.{model}: class not found")

        path.write_text("".join(pieces), encoding="utf-8")
    return changed


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode not in {"on", "off"}:
        sys.exit("usage: make_nullable.py on|off")
    count = toggle(BACKEND, mode == "on")
    print(f"{count} field(s) made {'nullable' if mode == 'on' else 'NOT NULL'}")