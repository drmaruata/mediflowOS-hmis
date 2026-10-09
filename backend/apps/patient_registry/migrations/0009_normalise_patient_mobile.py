"""Canonicalise stored patient mobiles to bare 10 digits (REG-003).

Before the fix, the registration serializer returned the contact dict
unchanged, so a registration carrying ``"+91 98765 43210"`` was stored
verbatim. The REG-003 duplicate probe prefilters with a substring match on the
*candidate's* bare digits, so a formatted stored value silently evaded the
match — a false negative. New writes now canonicalise in ``validate_contact``;
this migration brings rows written before the fix to the same stored shape, so
the prefilter (and, later, Task 12's ``mobile_idx`` hash) sees one canonical
form for every row regardless of when it was registered.

The normalisation is deliberately inlined rather than importing the app's
``normalise_mobile``: migrations must stay self-contained so they keep running
against the historical model if the helper evolves. The forward operation is
lossy by nature (formatting carries no identity information), so the reverse is
a documented no-op.
"""
import re

from django.db import migrations


def _canonical_mobile(value) -> str:
    """Reduce ``value`` to the bare 10-digit national form, mirroring
    ``validation.normalise_mobile`` at the time this migration ran."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("0"):
        digits = digits[1:]
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits[-10:] if len(digits) > 10 else digits


def canonicalise_mobiles(apps, schema_editor):
    """Rewrite ``contact.mobile`` to its canonical form on every patient row."""
    Patient = apps.get_model("patient_registry", "Patient")
    for patient in Patient.objects.all().iterator():
        contact = patient.contact
        if not isinstance(contact, dict):
            continue
        raw = contact.get("mobile")
        if raw in (None, ""):
            continue
        canonical = _canonical_mobile(raw)
        if canonical == raw:
            continue
        # ``update`` with the rewritten dict avoids clobbering a concurrently
        # changed row's other fields in a way ``save()`` on the full object
        # would not, and keeps the migration out of the app's model code.
        Patient.objects.filter(pk=patient.pk).update(
            contact={**contact, "mobile": canonical}
        )


class Migration(migrations.Migration):

    dependencies = [
        ("patient_registry", "0008_patient_intake_channel"),
    ]

    operations = [
        migrations.RunPython(canonicalise_mobiles, migrations.RunPython.noop),
    ]