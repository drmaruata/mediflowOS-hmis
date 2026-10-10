"""Consent persistence and link-token sealing for the ABDM callback.

Two of the seven architecture doc section 8.4 requirements close here:

**ABD-011** — "record the profile share as a consent event with timestamp,
source, purpose and facility". The event is written to ``abdm.consent_event``
inside the callback's transaction, so a consent record can never outlive the
patient it names: if the registration or the token write rolls back, the consent
row rolls back with it.

**ABD-012** — "store ABDM link tokens encrypted and use them only for
care-context linking". The token is sealed with the same AES-256-GCM envelope
``common.crypto`` gives patient identifiers (``v1:<iv>:<ciphertext>``) and never
leaves this module in plaintext: the acknowledgement does not echo it and
nothing logs it.

Data minimisation is a hard rule, not a preference. The shared profile the
gateway posts is *not* copied into the consent record. What is stored is the fact
and provenance of the consent, plus ``raw_profile_hash``: a one-way SHA-256 over
the canonical JSON of the payload, so an auditor can confirm a consent record
belongs to the payload in hand without the table holding any of it. The digest
is unkeyed and full-width on purpose — a keyed digest could only be reproduced
by this process, which makes the stored record unverifiable by anyone else, and
a truncated one turns collisions into a guessing game.
"""
import hashlib
import json
import uuid
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from common.crypto import derive_keys, encrypt

from .models import ABHACallbackLog, ConsentEvent


@lru_cache(maxsize=1)
def _aes_key() -> bytes:
    """The AES-256-GCM key link tokens are sealed under.

    Derived from ``PATIENT_FIELDS_KEY`` — the same passphrase stream
    ``apps.patient_registry.models.field_keys`` uses for ``abha_number``,
    ``abha_address`` and ``contact.mobile``. One key stream per installation
    means one rotation story and one thing to keep out of the environment's
    sight; a gateway-only passphrase would add a second secret with its own
    chance of being unset in production.

    Memoised because the derivation is deliberately expensive (PBKDF2,
    600k iterations) and every callback pays it.

    Refuses to derive under an empty passphrase: sealing a credential when there
    is no master key must raise rather than store something weaker.
    """
    passphrase = getattr(settings, "PATIENT_FIELDS_KEY", "")
    if not passphrase:
        raise ImproperlyConfigured(
            "PATIENT_FIELDS_KEY must be set to encrypt ABDM link tokens at "
            "rest (ABD-012)."
        )
    aes_key, _ = derive_keys(passphrase)
    return aes_key


def hash_profile(profile: dict) -> str:
    """One-way SHA-256 over the canonical JSON serialization of ``profile``.

    Canonical means sorted keys and no whitespace, so the digest of a payload
    does not depend on the order the gateway happened to serialize it in: two
    byte-identical payloads in different key order are the same consent and must
    hash alike, or an audit comparing a re-serialized payload against the stored
    digest would report a mismatch that never happened.
    """
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def record_consent_event(
    *,
    tenant_id: str,
    patient_id: uuid.UUID,
    request_id: str,
    source_app: str,
    purpose: str,
    facility_id: str,
    raw_profile_hash: str,
) -> ConsentEvent:
    """Write one consent event, tenant-scoped, and return it (ABD-011).

    Every argument is required: a consent record with a missing purpose or
    facility provenance is not usable as DPDP evidence, so none is defaulted.
    ``raw_profile_hash`` comes from :func:`hash_profile` — the caller passes it
    explicitly so the digest is computed from the payload the callback actually
    validated, not from whatever the model layer would serialise now.

    Must be called inside the caller's ``transaction.atomic()`` together with the
    patient registration and the token write, so the three commit or roll back
    as one.
    """
    return ConsentEvent.objects.create(
        tenant_id=tenant_id,
        patient_id=patient_id,
        request_id=request_id,
        source_app=source_app,
        purpose=purpose,
        facility_id=facility_id,
        raw_profile_hash=raw_profile_hash,
    )


def store_link_token(*, log_id: uuid.UUID, token: str) -> None:
    """Seal ``token`` into ``ABHACallbackLog.link_token_enc`` (ABD-012).

    Scoped by the log row's id rather than by tenant: the row was created
    moments earlier inside the caller's transaction and the id is a primary key,
    so there is no lookup for a tenant filter to mis-scope. The write still
    belongs inside that same transaction — a sealed token outliving its log row
    would be an orphaned credential.

    ``update_fields`` is not an optimisation: it keeps ``timestamp`` and
    ``status`` (server-owned, set at create) from being rewritten from the
    in-memory copy.

    The plaintext is neither returned nor logged. The sealed value is all this
    function leaves behind.
    """
    log = ABHACallbackLog.objects.get(id=log_id)
    log.link_token_enc = encrypt(token, key=_aes_key())
    log.save(update_fields=["link_token_enc"])
