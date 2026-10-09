"""Patient registry models (REG-001 to REG-013, ABD-001 to ABD-017).

REG-008: ``abha_number``, ``abha_address`` and ``contact.mobile`` are sensitive
identifiers and are stored encrypted at rest. The database columns hold ``v1:``
AES-GCM tokens plus deterministic keyed-HMAC ``*_idx`` columns for exact
lookups; the model exposes plaintext (properties / decrypt-on-load) and the
serializer round-trips plaintext. See ``common/crypto.py`` for the token format
and rationale.
"""
import uuid
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

from common.crypto import (
    TOKEN_PREFIX,
    decrypt,
    derive_keys,
    encrypt,
    search_index,
)
from .validation import normalise_mobile


#: How the patient reached the counter (REG-005). This is a different axis from
#: :class:`IntakePoint.type`, which is the *kind of service point*
#: (``opd``/``pharmacy``/``lab``/``billing``); the two sets do not overlap and
#: are never interchangeable. REG-005 enumerates the channel set, so it lives
#: here as the single source the serializer validates against.
INTAKE_CHANNELS = (
    ("counter", "Counter"),
    ("abha_qr", "ABHA QR (Scan and Share)"),
    ("appointment", "Appointment"),
)


@lru_cache(maxsize=1)
def field_keys():
    """The (aes_key, hmac_key) pair for REG-008, from ``PATIENT_FIELDS_KEY``.

    One accessor for the model layer, the queryset helpers, the views and the
    ABDM gateway so every consumer derives from the same key stream. Refuses to
    derive under a missing passphrase: encrypting patient identifiers without a
    master key must never silently happen (the settings guard in base.py is the
    first line, this is the second, at the point of use).
    """
    passphrase = getattr(settings, "PATIENT_FIELDS_KEY", "")
    if not passphrase:
        raise ImproperlyConfigured(
            "PATIENT_FIELDS_KEY must be set to encrypt patient identifiers at "
            "rest (REG-008)."
        )
    return derive_keys(passphrase)


class EncryptedMobileField(models.JSONField):
    """JSON field that seals ``contact["mobile"]`` at the database boundary.

    The sealer runs in ``get_db_prep_value``, so the in-memory attribute (and
    therefore every serializer response) keeps plaintext while the stored JSON
    carries a ``v1:`` token — the two never have to be reconciled. The mobile is
    canonicalised to the bare 10-digit form *here* as well as in the
    serializer's ``validate_contact`` because writers that bypass the
    serializer (the ABDM gateway, direct ``Patient.objects.create`` calls) must
    still index-match a canonical probe through ``mobile_idx``.
    """

    def get_db_prep_value(self, value, connection, prepared=False):
        return super().get_db_prep_value(self._seal(value), connection, prepared)

    @staticmethod
    def _seal(value):
        """Canonicalise and encrypt ``value["mobile"]``, leaving other keys and
        shapes untouched. A value that is already a ``v1:`` token passes through
        unchanged — re-sealing would double-encrypt and permanently destroy the
        plaintext."""
        if not isinstance(value, dict):
            return value
        mobile = value.get("mobile")
        if mobile in (None, ""):
            return value
        if isinstance(mobile, str) and mobile.startswith(TOKEN_PREFIX):
            return value
        aes_key, _ = field_keys()
        canonical = normalise_mobile(mobile)
        return {**value, "mobile": encrypt(canonical or mobile, key=aes_key)}


class PatientQuerySet(models.QuerySet):
    """Queryset helpers for REG-008's exact-match index columns.

    The HMAC index contains no plaintext, so lookups are exact-digest equality
    only. A *partial* probe (``"9876"``) has nothing to match — that is
    deliberate: ciphertext cannot be substring-matched, and the degradation is
    pinned by tests/integration/test_patient_encryption.py.
    """

    def filter_by_mobile(self, tenant_id, mobile):
        """Rows whose canonical mobile hashes to ``mobile``, tenant-scoped.

        The probe is canonicalised exactly like the write path, so a formatted
        ``+91``/spaced probe meets a row stored as the bare national number.
        ``tenant_id`` is a required argument, never a default: a caller that
        forgets the scope must fail loudly, not cross tenants.
        """
        canonical = normalise_mobile(mobile)
        _, hmac_key = field_keys()
        return self.filter(
            tenant_id=tenant_id,
            mobile_idx=search_index(canonical, key=hmac_key),
        )

    def filter_by_abha(self, tenant_id, abha_number):
        """Rows whose ABHA number hashes to ``abha_number``, tenant-scoped."""
        probe = str(abha_number or "").strip()
        if not probe:
            return self.none()
        _, hmac_key = field_keys()
        return self.filter(
            tenant_id=tenant_id,
            abha_number_idx=search_index(probe, key=hmac_key),
        )


class PatientManager(models.Manager.from_queryset(PatientQuerySet)):
    """Default manager exposing :class:`PatientQuerySet` helpers."""


class Patient(models.Model):
    """Single patient record per tenant (UHID-based).

    REG-008: ``abha_number`` and ``abha_address`` are stored as AES-GCM tokens
    in the underscore-prefixed ``_abha_*`` storage columns (``db_column``
    preserves the pre-0010 column names so the migration encrypts rows in
    place); ``contact.mobile`` is sealed inside the JSON by
    :class:`EncryptedMobileField`. The properties and queryset helpers are the
    plaintext interface; everything below them in the ORM sees tokens.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    uhid = models.CharField(max_length=32, db_index=True)
    # --- REG-008 encrypted identifier storage -----------------------------
    # Storage attributes are deliberately underscore-prefixed: production code
    # reads/writes the plaintext properties, and a public ``abha_number`` field
    # would tempt a ``filter(abha_number="...")`` that silently searches
    # ciphertext. The ``*_idx`` columns are the deterministic keyed-HMAC values
    # that REG-002/REG-003 matching actually filters on.
    # ``max_length`` is the *token* bound, not the plaintext bound: a 128-char
    # plaintext (the serializer's upper limit) seals into a 212-char ``v1:``
    # token (3-char prefix + 16-char base64 IV + ":" + base64 of the plaintext
    # plus the 16-byte GCM tag = 4*ceil(144/3) = 192). 256 gives ~44-char
    # headroom; the physical column is widened by migration 0010 (expand-only)
    # so an oversized legacy row fails loudly on PostgreSQL instead of being
    # silently truncated on SQLite.
    _abha_number = models.CharField(
        max_length=256, null=True, blank=True, db_column="abha_number"
    )
    _abha_address = models.CharField(
        max_length=256, null=True, blank=True, db_column="abha_address"
    )
    abha_number_idx = models.CharField(max_length=64, null=True, blank=True)
    abha_address_idx = models.CharField(max_length=64, null=True, blank=True)
    mobile_idx = models.CharField(max_length=64, null=True, blank=True)
    # ----------------------------------------------------------------------
    verification_status = models.CharField(max_length=16, default="pending")  # pending | verified
    verified_at = models.DateTimeField(null=True, blank=True)
    # REG-005. ``blank`` + empty default is the expand-only, non-breaking shape:
    # existing rows predate the column and are backfilled to "unrecorded"
    # rather than mislabelled as counter registrations. New registrations carry
    # a real value from the counter UI.
    intake_channel = models.CharField(
        max_length=16, blank=True, default="", choices=INTAKE_CHANNELS
    )
    demographics = models.JSONField()
    # REG-008: ``mobile`` inside this JSON is encrypted at rest (the DB value is
    # a ``v1:`` token); the model attribute is decrypted on load so callers
    # always work with plaintext.
    contact = EncryptedMobileField(null=True)
    address = models.JSONField(null=True)
    scheme_category = models.JSONField(null=True)
    consent_flags = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PatientManager()

    class Meta:
        db_table = "registry.patient"
        indexes = [
            # REG-002/REG-003 lookups filter on the HMAC digests, so the
            # composite indexes lead with tenant_id exactly like every other
            # tenant-owned index in this schema.
            models.Index(fields=["tenant_id", "uhid"]),
            models.Index(fields=["tenant_id", "mobile_idx"]),
            models.Index(fields=["tenant_id", "abha_number_idx"]),
            models.Index(fields=["tenant_id", "abha_address_idx"]),
        ]
        # UHID is unique *within a tenant*, not globally: the class docstring
        # promises one record per tenant. A bare unique=True would stop two
        # hospitals from both issuing UH0001.
        unique_together = [["tenant_id", "uhid"]]

    # --- plaintext interface over the encrypted storage -------------------

    @staticmethod
    def _decrypt_value(stored):
        """Open a stored token; pass non-token values through unchanged.

        The pass-through is load-bearing for the 0010 migration's reverse: a
        rolled-back row holds plaintext again and reading it must not raise.
        """
        if stored in (None, ""):
            return stored
        if not stored.startswith(TOKEN_PREFIX):
            return stored
        aes_key, _ = field_keys()
        return decrypt(stored, key=aes_key)

    @staticmethod
    def _seal_value(plaintext, aes_key):
        """Encrypt a plaintext value; never re-encrypt an existing token."""
        if plaintext in (None, ""):
            return plaintext
        if plaintext.startswith(TOKEN_PREFIX):
            return plaintext
        return encrypt(plaintext, key=aes_key)

    @property
    def abha_number(self):
        """Plaintext ABHA number; the storage column holds a ``v1:`` token."""
        return self._decrypt_value(self._abha_number)

    @abha_number.setter
    def abha_number(self, value):
        aes_key, _ = field_keys()
        self._abha_number = self._seal_value(value, aes_key)

    @property
    def abha_address(self):
        """Plaintext ABHA address; the storage column holds a ``v1:`` token."""
        return self._decrypt_value(self._abha_address)

    @abha_address.setter
    def abha_address(self, value):
        aes_key, _ = field_keys()
        self._abha_address = self._seal_value(value, aes_key)

    @classmethod
    def from_db(cls, db, field_names, values):
        """Decrypt ``contact["mobile"]`` when a row is loaded from the DB.

        This lives here (not in the contact field's ``from_db_value``) because
        ``values()`` also applies field converters: the at-rest assertions in
        test_patient_encryption.py read the raw stored token through
        ``values()``, so decryption must only happen when an actual model
        instance is built.
        """
        instance = super().from_db(db, field_names, values)
        if "contact" in field_names:
            contact = instance.contact
            mobile = contact.get("mobile") if isinstance(contact, dict) else None
            if isinstance(mobile, str) and mobile.startswith(TOKEN_PREFIX):
                aes_key, _ = field_keys()
                instance.contact = {
                    **contact,
                    "mobile": decrypt(mobile, key=aes_key),
                }
        return instance

    def save(self, *args, **kwargs):
        """Refresh the HMAC index columns before persisting.

        The digests are deterministic, so recomputing them on every save is
        safe (byte-identical for unchanged values) and guarantees the index and
        the ciphertext can never drift apart.
        """
        self._sync_search_indexes()
        super().save(*args, **kwargs)

    def _sync_search_indexes(self):
        """Write ``*_idx`` digests from this instance's plaintext values."""
        _, hmac_key = field_keys()
        abha_number = self.abha_number or ""
        abha_address = self.abha_address or ""
        contact = self.contact if isinstance(self.contact, dict) else {}
        mobile = contact.get("mobile") or ""
        self.abha_number_idx = (
            search_index(abha_number, key=hmac_key) if abha_number else ""
        )
        self.abha_address_idx = (
            search_index(abha_address, key=hmac_key) if abha_address else ""
        )
        # The digest must cover exactly the string that got sealed
        # (EncryptedMobileField._seal encrypts ``canonical or mobile``).
        # Indexing ``normalise_mobile(mobile)`` alone would diverge for a
        # non-canonicalisable value (e.g. ``"abc"`` → index of ``""`` while the
        # seal holds ``encrypt("abc")``), leaving no way to match the row.
        canonical = normalise_mobile(mobile) if mobile else ""
        self.mobile_idx = (
            search_index(canonical or mobile, key=hmac_key) if mobile else ""
        )


class IntakePoint(models.Model):
    """Generic intake point model for Scan and Share extensibility."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    facility = models.ForeignKey("identity_tenancy.Facility", on_delete=models.CASCADE, related_name="intake_points", db_index=True)
    type = models.CharField(max_length=32)  # opd|pharmacy|lab|billing
    counter_id = models.CharField(max_length=32, null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "registry.intake_point"
        indexes = [models.Index(fields=["tenant_id", "facility", "type"])]


class QRCode(models.Model):
    """Facility/counter/department QR codes for ABDM Scan and Share."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    facility = models.ForeignKey("identity_tenancy.Facility", on_delete=models.CASCADE, related_name="qr_codes", db_index=True)
    intake_point = models.ForeignKey(IntakePoint, on_delete=models.SET_NULL, null=True, blank=True, related_name="qr_codes")
    encode_data = models.TextField()  # ABDM HIP ID + intake code
    active = models.BooleanField(default=True)
    regenerated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "registry.qr_code"
        indexes = [models.Index(fields=["tenant_id", "facility", "active"])]


class ABHACallbackLog(models.Model):
    """Idempotent log of ABDM profile-share callbacks."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    request_id = models.CharField(max_length=128, unique=True, db_index=True)
    facility_abdm_id = models.CharField(max_length=64, db_index=True)
    ip = models.GenericIPAddressField(null=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    profile = models.JSONField(null=True)
    matched_patient_id = models.UUIDField(null=True, blank=True)
    token_issued = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=32)  # ok | rejected | duplicate

    class Meta:
        db_table = "registry.abdm_callback_log"
        indexes = [models.Index(fields=["tenant_id", "request_id"])]


class PatientSequence(models.Model):
    """Per-tenant, per-month counter that backs server-issued UHIDs (REG-001).

    One row exists per ``(tenant, kind, period)``; ``next_value`` is the next
    number to issue, so the first call creates the row at 1 and leaves it at
    2. ``period`` is the ``%Y-%m`` month of registration, which is what makes
    a UHID restart at ``000001`` each month and stay unique within the tenant.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    kind = models.CharField(max_length=16, default="uhid")
    period = models.CharField(max_length=16)
    next_value = models.BigIntegerField(default=1)

    class Meta:
        db_table = "registry.sequence"
        unique_together = [["tenant_id", "kind", "period"]]