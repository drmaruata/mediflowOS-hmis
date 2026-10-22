"""Unit tests for the ABDM consent write path (ABD-011, ABD-012).

``tests/integration/test_abdm_callback.py`` pins both requirements end to end
through the callback. These tests cover what that file cannot reach cleanly:
the two primitives in ``apps.abdm_gateway.consent`` on their own terms.

``hash_profile`` must be reproducible by anyone holding the payload (canonical
serialization, one-way, full width) — a keyed or truncated digest would silently
make the stored record unverifiable. ``store_link_token`` must seal the token
under the very same key stream the patient registry encrypts identifiers with,
because a second passphrase would mean a second key to rotate and leak; that
coupling is asserted here rather than assumed.
"""
import hashlib
import json
import uuid

import pytest
from django.conf import settings

from apps.abdm_gateway.consent import (
    _aes_key,
    hash_profile,
    record_consent_event,
    store_link_token,
)
from apps.abdm_gateway.models import ABHACallbackLog, ConsentEvent
from apps.patient_registry.models import field_keys
from common.crypto import TOKEN_PREFIX, decrypt

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

TENANT_ID = uuid.uuid4()
PATIENT_ID = uuid.uuid4()
FACILITY_ID = uuid.uuid4()


def _consent_event(**overrides):
    """A consent-event write with every argument the interface declares."""
    kwargs = {
        "tenant_id": str(TENANT_ID),
        "patient_id": PATIENT_ID,
        "request_id": "req-consent-1",
        "source_app": "ABDM",
        "purpose": "registration",
        "facility_id": str(FACILITY_ID),
        "raw_profile_hash": "ab" * 32,
    }
    kwargs.update(overrides)
    return record_consent_event(**kwargs)


# --- hash_profile -------------------------------------------------------------


def test_hash_profile_is_the_sha256_of_the_canonical_json():
    """The digest is specified, not incidental: sorted keys, no whitespace."""
    profile = {"abhaNumber": "123456789012", "demographics": {"yearOfBirth": 1984}}

    assert hash_profile(profile) == hashlib.sha256(
        json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_hash_profile_ignores_key_order():
    """Serialization order is the gateway's choice, not part of the payload.

    Two byte-identical payloads in different key order are the same consent, so
    they must hash alike; otherwise an audit comparing a re-serialized payload
    against the stored digest would report a mismatch that never happened.
    """
    assert hash_profile({"a": 1, "b": 2}) == hash_profile({"b": 2, "a": 1})


def test_hash_profile_separates_different_payloads():
    assert hash_profile({"abhaNumber": "111111111111"}) != hash_profile(
        {"abhaNumber": "222222222222"}
    )


def test_hash_profile_is_a_full_width_hex_digest():
    """No truncation: a short digest makes collisions a matter of guessing."""
    digest = hash_profile({"x": 1})
    assert len(digest) == 64
    int(digest, 16)  # hex, so nothing was substituted for a real digest


# --- record_consent_event -----------------------------------------------------


def test_record_consent_event_persists_every_declared_field():
    """The signature is the contract the view calls; one write, one row."""
    event = _consent_event(request_id="req-consent-2")

    assert ConsentEvent.objects.count() == 1
    stored = ConsentEvent.objects.get()
    assert stored.id == event.id
    assert stored.tenant_id == TENANT_ID
    assert stored.patient_id == PATIENT_ID
    assert stored.request_id == "req-consent-2"
    assert stored.source_app == "ABDM"
    assert stored.purpose == "registration"
    assert stored.facility_id == FACILITY_ID
    assert stored.granted_at is not None
    assert stored.raw_profile_hash == "ab" * 32


def test_record_consent_event_refuses_a_duplicate_grant():
    """The DB constraint backs the view's idempotency up (ABD-006, ABD-011).

    The view returns early on a replayed request ID before any write, so this
    second line of defence exists for a code path that forgets to: two consent
    rows for one gateway request is two records of the same grant, and no DPDP
    audit can reconcile that.
    """
    from django.db import IntegrityError, transaction

    _consent_event()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _consent_event()

    assert ConsentEvent.objects.count() == 1


def test_record_consent_event_never_writes_profile_data():
    """Data minimisation at the write path, not only at the read path."""
    _consent_event()

    row = ConsentEvent.objects.values().get()
    assert set(row) == {
        "id",
        "tenant_id",
        "patient_id",
        "request_id",
        "source_app",
        "purpose",
        "facility_id",
        "granted_at",
        "raw_profile_hash",
    }
    assert "name" not in row and "abha_number" not in row


# --- store_link_token ---------------------------------------------------------


def test_store_link_token_seals_the_token_and_round_trips():
    """ABD-012: the column holds a `v1:` envelope that opens to the token."""
    log = ABHACallbackLog.objects.create(
        tenant_id=TENANT_ID,
        request_id="req-seal-1",
        facility_abdm_id="hip-seal",
        status="ok",
    )

    store_link_token(log_id=log.id, token="a-known-link-token")

    log.refresh_from_db()
    assert log.link_token_enc != "a-known-link-token"
    assert log.link_token_enc.startswith(TOKEN_PREFIX)
    assert decrypt(log.link_token_enc, key=_aes_key()) == "a-known-link-token"


def test_store_link_token_reuses_the_reg_008_key_stream():
    """One passphrase, one key stream — no second key to rotate or leak.

    The link token is sealed under the AES key derived from
    ``PATIENT_FIELDS_KEY``, exactly as ``patient_registry`` seals ``abha_number``
    and ``contact.mobile``. A separate passphrase for the gateway would be a
    second secret with its own rotation story and its own chance of being unset.
    """
    patient_aes_key, _ = field_keys()

    assert _aes_key() == patient_aes_key
    assert len(_aes_key()) == 32


def test_store_link_token_refuses_a_missing_master_key(monkeypatch):
    """Sealing under an absent key must raise, not store something weaker."""
    from django.core.exceptions import ImproperlyConfigured

    log = ABHACallbackLog.objects.create(
        tenant_id=TENANT_ID,
        request_id="req-seal-2",
        facility_abdm_id="hip-seal",
        status="ok",
    )
    monkeypatch.setattr(settings, "PATIENT_FIELDS_KEY", "")
    # _aes_key is memoised per process, so the cache has to be cleared for the
    # override to be visible — the same reason the real guard lives in settings.
    _aes_key.cache_clear()

    with pytest.raises(ImproperlyConfigured):
        store_link_token(log_id=log.id, token="never-sealed")

    log.refresh_from_db()
    assert log.link_token_enc is None


def test_store_link_token_updates_only_the_sealed_column():
    """``update_fields`` keeps the log row's own columns untouched.

    The log row was created earlier in the same transaction; a full ``save()``
    would rewrite ``timestamp`` and ``status`` from the in-memory copy.
    """
    log = ABHACallbackLog.objects.create(
        tenant_id=TENANT_ID,
        request_id="req-seal-3",
        facility_abdm_id="hip-seal",
        status="ok",
    )
    original_timestamp = log.timestamp

    store_link_token(log_id=log.id, token="another-link-token")

    log.refresh_from_db()
    assert log.timestamp == original_timestamp
    assert log.status == "ok"
    assert log.link_token_enc is not None
