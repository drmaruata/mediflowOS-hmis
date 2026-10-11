"""Pure hash-chain arithmetic for the audit log (AUD-002).

No database: every case here exercises ``chain_digest`` directly, because the
chain's tamper-evidence rests on the digest's own properties — determinism,
key binding, prev-hash chaining, and canonicalisation of the values writers
actually pass (a UUID/datetime/None mix) — rather than on any ORM behaviour.
Anything needing a row or an endpoint lives in
``tests/integration/test_audit_trail.py`` instead; pinning the digest here
keeps the arithmetic reviewable without a database in the way.
"""
import datetime
import uuid

import pytest

from apps.audit.services import chain_digest

#: Matches the deterministic literal ``config.settings.test`` installs, so the
#: digests below are reproducible on any host.
KEY = "kepi-21-unit-passphrase"


class TestDigestDeterminism:
    """A digest is a pure function, or verification cannot be recomputed."""

    def test_same_inputs_give_the_same_digest(self):
        """No salt, no clock, no randomness: the verifier must be able to
        rebuild a digest that was written minutes or years ago."""
        fields = {"action": "read", "entity_id": "P1"}

        first = chain_digest(KEY, "prev", fields)
        second = chain_digest(KEY, "prev", fields)

        assert first == second

    def test_digest_is_a_sha256_hex_string(self):
        """The 128-character column holds a hex sha256, not a truncated one."""
        digest = chain_digest(KEY, "", {})

        assert len(digest) == 64
        assert all(character in "0123456789abcdef" for character in digest)


class TestCanonicalisation:
    """Canonical form is what makes a recomputed digest land on the same one."""

    def test_field_order_is_irrelevant(self):
        """Keys are sorted, so the digest cannot depend on insertion order.

        The three writers build their field dicts in different shapes (the
        mixin passes ``reason``, ``audit_read`` does not, the QR path passes
        ``source``), so an order-sensitive digest would verify for one writer
        and fail for another for no reason an operator could act on.
        """
        assert chain_digest(KEY, "prev", {"action": "read", "entity_id": "P1"}) == (
            chain_digest(KEY, "prev", {"entity_id": "P1", "action": "read"})
        )

    def test_uuid_datetime_and_none_values_serialise(self):
        """``default=str`` keeps the non-JSON values every writer passes.

        ``user_id`` reaches the chain as an int pk that the row coerces to a
        UUID, ``reason``/``source`` are frequently ``None``, and a stamp is a
        datetime. A digest that raised ``TypeError`` on any of them would
        leave the row unhashed — an unchained row in the middle of the chain.
        """
        fields = {
            "user_id": uuid.UUID(int=7),
            "reason": None,
            "source_ip": None,
            "stamp": datetime.datetime(
                2026, 10, 10, 12, 0, tzinfo=datetime.timezone.utc
            ),
            "entity_id": "P1",
        }

        assert chain_digest(KEY, "", fields) == chain_digest(KEY, "", dict(fields))

    def test_changing_one_field_value_changes_the_digest(self):
        """A substituted field must not land on the same digest.

        An in-place ``UPDATE`` is the attack the chain exists to catch: if a
        changed ``entity_id`` still verified, the log would be tamper-*tolerant*
        rather than tamper-evident.
        """
        original = chain_digest(KEY, "prev", {"action": "read", "entity_id": "P1"})
        mutated = chain_digest(KEY, "prev", {"action": "delete", "entity_id": "P1"})

        assert original != mutated


class TestKeyAndPrevBindings:
    """The two inputs a forger would have to reproduce."""

    def test_a_different_key_gives_a_different_digest(self):
        """Without key binding the chain would be verifiable by anyone who can
        read the table — which is exactly who is being defended against."""
        fields = {"action": "read", "entity_id": "P1"}

        assert chain_digest(KEY, "", fields) != chain_digest("another-key", "", fields)

    def test_prev_hash_changes_the_digest(self):
        """Each row commits to its predecessor's hash, which is what turns a
        set of individually-verified rows into a chain."""
        fields = {"action": "read", "entity_id": "P1"}

        assert chain_digest(KEY, "prev-a", fields) != chain_digest(KEY, "prev-b", fields)

    def test_empty_key_is_refused(self):
        """Defence in depth behind the settings guard.

        An unkeyed HMAC-SHA256 is just a hash, so anyone who can recompute it
        could also forge it and the chain would attest nothing.
        ``config.settings.base`` already refuses to import under a non-DEBUG
        with ``AUDIT_HMAC_KEY`` unset; this makes the digest refuse on its own
        so a future caller cannot bypass that guard by accident.
        """
        with pytest.raises(ValueError, match="AUDIT_HMAC_KEY"):
            chain_digest("", "prev", {"action": "read"})
