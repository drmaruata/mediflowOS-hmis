"""Encrypt patient identifiers at rest (REG-008).

``abha_number``, ``abha_address`` and ``contact.mobile`` move from plaintext
columns to ``v1:`` AES-GCM tokens. The public column names are preserved via
``db_column`` on the underscore-prefixed storage fields (``_abha_number`` /
``_abha_address``), so this migration encrypts the existing rows **in place**:
the field is renamed to ``_abha_number`` but keeps the ``abha_number`` column,
widened from 14 to 128 characters. The ``*_idx`` columns are the deterministic
keyed-HMAC digests that REG-002 search and REG-003 duplicate detection filter
on once the real values are ciphertext.

The forward data operation reads the raw stored values through ``values()``
(bypassing the model's decrypt-on-load), encrypts the plaintext columns and
writes the matching index digests. It is idempotent: a value that already
starts with the ``v1:`` token prefix is left untouched, so re-running the
migration never double-encrypts (which would permanently destroy the
plaintext) and never changes an existing token. The reverse operation restores
the plaintext columns so a rollback is lossless.

Like 0009, the data operations stay self-contained: the mobile normaliser is
inlined rather than imported from the app, and the only app-layer dependency
is the pinned ``common.crypto`` token format. Writing the encrypted ``contact``
JSON goes through the ORM's ``update()`` because the historical field's sealer
passes existing tokens through unchanged; writing the reverse (plaintext) would
re-seal, so the reverse uses a raw ``UPDATE`` on the quoted table/column names.
"""
import json

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, migrations, models

import apps.patient_registry.models  # EncryptedMobileField for the contact AlterField
from common.crypto import TOKEN_PREFIX, decrypt, derive_keys, encrypt, search_index


def _canonical_mobile(value) -> str:
    """Reduce ``value`` to the bare 10-digit national form, mirroring
    ``validation.normalise_mobile`` at the time this migration ran (see 0009)."""
    import re

    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("0"):
        digits = digits[1:]
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits[-10:] if len(digits) > 10 else digits


def _keys():
    """The (aes_key, hmac_key) pair derived from ``PATIENT_FIELDS_KEY``.

    Refuses to derive under a missing passphrase exactly like the app's
    ``models.field_keys``: a migration must never encrypt patient identifiers
    under an empty master key.
    """
    passphrase = getattr(settings, "PATIENT_FIELDS_KEY", "")
    if not passphrase:
        raise ImproperlyConfigured(
            "PATIENT_FIELDS_KEY must be set to encrypt patient identifiers at "
            "rest (REG-008)."
        )
    return derive_keys(passphrase)


def encrypt_existing_rows(apps, schema_editor):
    """Encrypt every existing plaintext identifier row (REG-008 forward)."""
    aes_key, hmac_key = _keys()
    Patient = apps.get_model("patient_registry", "Patient")
    rows = Patient.objects.values("pk", "_abha_number", "_abha_address", "contact")
    for row in rows.iterator():
        updates = {}
        # ABHA number / address: encrypt a plaintext value, leave a token alone.
        for column, idx_column, plaintext in (
            ("_abha_number", "abha_number_idx", row["_abha_number"]),
            ("_abha_address", "abha_address_idx", row["_abha_address"]),
        ):
            if plaintext in (None, "") or plaintext.startswith(TOKEN_PREFIX):
                continue
            updates[column] = encrypt(plaintext, key=aes_key)
            updates[idx_column] = search_index(plaintext, key=hmac_key)
        # Mobile: canonicalise, seal inside the contact JSON, index the digest.
        contact = row["contact"] if isinstance(row["contact"], dict) else None
        if contact is not None:
            mobile = contact.get("mobile")
            if mobile not in (None, "") and not (
                isinstance(mobile, str) and mobile.startswith(TOKEN_PREFIX)
            ):
                canonical = _canonical_mobile(mobile) or str(mobile)
                updates["contact"] = {
                    **contact,
                    "mobile": encrypt(canonical, key=aes_key),
                }
                updates["mobile_idx"] = search_index(canonical, key=hmac_key)
        if updates:
            # ``update`` runs the field sealer (historical or real model), which
            # passes ``v1:`` tokens through — this is what keeps a re-run from
            # double-encrypting and destroying the plaintext.
            Patient.objects.filter(pk=row["pk"]).update(**updates)


def decrypt_existing_rows(apps, schema_editor):
    """Restore the plaintext columns (REG-008 reverse, lossless rollback)."""
    aes_key, _ = _keys()
    Patient = apps.get_model("patient_registry", "Patient")
    table = connection.ops.quote_name(Patient._meta.db_table)
    contact_column = connection.ops.quote_name(
        Patient._meta.get_field("contact").column
    )
    pk_column = connection.ops.quote_name(Patient._meta.pk.column)
    rows = Patient.objects.values("pk", "_abha_number", "_abha_address", "contact")
    with connection.cursor() as cursor:
        for row in rows.iterator():
            updates = {}
            for column, stored in (
                ("_abha_number", row["_abha_number"]),
                ("_abha_address", row["_abha_address"]),
            ):
                if isinstance(stored, str) and stored.startswith(TOKEN_PREFIX):
                    updates[column] = decrypt(stored, key=aes_key)
            contact = row["contact"] if isinstance(row["contact"], dict) else None
            mobile = contact.get("mobile") if contact is not None else None
            if isinstance(mobile, str) and mobile.startswith(TOKEN_PREFIX):
                updates["contact"] = {
                    **contact,
                    "mobile": decrypt(mobile, key=aes_key),
                }
            if not updates:
                continue
            char_updates = {k: v for k, v in updates.items() if k != "contact"}
            if char_updates:
                # Plain CharFields — the ORM writes them verbatim.
                Patient.objects.filter(pk=row["pk"]).update(**char_updates)
            if "contact" in updates:
                # Raw SQL: writing the plaintext through the field would re-seal
                # it into a new token, stranding the rollback. The pk is bound
                # through the field's get_db_prep_value so the WHERE matches on
                # every backend (SQLite stores UUIDs as compact hex, PostgreSQL
                # stores them natively — a plain str() of the UUID misses on
                # SQLite and would silently update zero rows).
                pk_value = Patient._meta.pk.get_db_prep_value(
                    row["pk"], connection
                )
                cursor.execute(
                    f"UPDATE {table} SET {contact_column} = %s WHERE {pk_column} = %s",
                    [json.dumps(updates["contact"]), pk_value],
                )


class Migration(migrations.Migration):

    dependencies = [
        ('patient_registry', '0009_normalise_patient_mobile'),
    ]

    operations = [
        # The old (tenant_id, abha_number) composite index references a column
        # the model no longer exposes; the HMAC index replaces it below.
        migrations.RemoveIndex(
            model_name='patient',
            name='registry.pa_tenant__097a2a_idx',
        ),
        # REG-008: rename the public fields to the underscore storage fields
        # while preserving the physical column names via db_column, so the data
        # operation below encrypts rows in place rather than in a new table.
        migrations.RenameField(
            model_name='patient',
            old_name='abha_number',
            new_name='_abha_number',
        ),
        migrations.AlterField(
            model_name='patient',
            name='_abha_number',
            field=models.CharField(blank=True, db_column='abha_number', max_length=128, null=True),
        ),
        migrations.AlterField(
            model_name='patient',
            name='abha_address',
            field=models.CharField(blank=True, db_column='abha_address', max_length=128, null=True),
        ),
        migrations.RenameField(
            model_name='patient',
            old_name='abha_address',
            new_name='_abha_address',
        ),
        # Deterministic search-index digests (keyed HMAC-SHA256, no plaintext).
        migrations.AddField(
            model_name='patient',
            name='abha_address_idx',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='patient',
            name='abha_number_idx',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='patient',
            name='mobile_idx',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='patient',
            name='contact',
            field=apps.patient_registry.models.EncryptedMobileField(null=True),
        ),
        migrations.AddIndex(
            model_name='patient',
            index=models.Index(fields=['tenant_id', 'mobile_idx'], name='registry.pa_tenant__bc6d6b_idx'),
        ),
        migrations.AddIndex(
            model_name='patient',
            index=models.Index(fields=['tenant_id', 'abha_number_idx'], name='registry.pa_tenant__ed5085_idx'),
        ),
        migrations.AddIndex(
            model_name='patient',
            index=models.Index(fields=['tenant_id', 'abha_address_idx'], name='registry.pa_tenant__0ad8f3_idx'),
        ),
        migrations.RunPython(encrypt_existing_rows, decrypt_existing_rows),
    ]