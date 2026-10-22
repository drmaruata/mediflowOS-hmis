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

#: Fixed tenant ids for :class:`TestChainLockKeyRange`. Six drawn whose
#: 64-bit-truncated key lands at or above ``2**63`` (the overflow half of the
#: uuid4 space) and six whose key is already in range: a parametrised pin over
#: the whole span, fixed so a regression cannot hide behind fresh randomness.
OVERFLOW_HALF_TENANTS = (
    "1ecfb853-5c12-4c4f-8b2f-8175611a7438",
    "bbd8db73-6bdc-43a9-9c15-baa40ccc3f09",
    "de30cb1d-ac26-4a39-9917-0ca3861dd8dc",
    "142c2af1-6bb6-4fd3-9cfe-bb30ad788e26",
    "d4b16440-4438-4bd0-a346-b8fea5c1734a",
    "f1cc19d6-50b5-422f-9c21-bea0568ee68d",
)
IN_RANGE_HALF_TENANTS = (
    "b0b8b5af-7280-45da-9a7e-11605a145cbf",
    "23697920-30fc-4d9b-8aa8-438609e103c9",
    "13024006-ac21-47c5-aac4-7717f29f47e8",
    "bfee9599-819c-4bdc-a3d4-8059cb58f77f",
    "2484fb92-bbe8-4af5-af85-873cdbcff932",
    "b361b6b6-a716-442b-a7a8-a54cca11f8ff",
)


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


class TestChainLockKeyRange:
    """The advisory-lock key must fit a signed bigint (AUD-002, PostgreSQL).

    ``_lock_tenant_chain`` hands the key to ``pg_advisory_xact_lock(%s)``,
    whose single-argument form takes a ``bigint``. psycopg3 routes any int at
    or above ``2**63`` to the numeric dumper, and PostgreSQL then fails
    function resolution — so an out-of-range key raises inside
    ``append_event``'s atomic block and the audited write 500s. The fast suite
    runs on SQLite, which never takes the lock, so the range is pinned here
    against the whole uuid4 space instead: every fixed tenant id must derive a
    key in ``[0, 2**63)``.
    """

    @pytest.mark.parametrize(
        "tenant_id", OVERFLOW_HALF_TENANTS + IN_RANGE_HALF_TENANTS
    )
    def test_key_is_a_non_negative_signed_bigint(self, tenant_id):
        from apps.audit.services import _chain_lock_key

        key = _chain_lock_key(uuid.UUID(tenant_id))

        assert isinstance(key, int)
        assert 0 <= key < 2**63

    def test_key_is_stable_and_decisive(self):
        """Same tenant, same key every process: the lock must actually collide.

        The derivation is a sha256, not :func:`hash`, precisely so two workers
        serialise on the same number; a salt would give different locks for
        the same tenant and the guard would silently vanish.
        """
        from apps.audit.services import _chain_lock_key

        tenant_id = uuid.UUID(OVERFLOW_HALF_TENANTS[0])

        assert _chain_lock_key(tenant_id) == _chain_lock_key(
            uuid.UUID(str(tenant_id))
        )


class TestCanonicalFieldCoercion:
    """Hashed == stored: the canonical dict carries the coerced value.

    Both sides of verification read through :func:`_canonical_fields`, so the
    digest written and the digest recomputed agree only if the value hashed is
    the value the row stores. Coercing through each field's own ``to_python``
    — the conversion ``save`` performs — makes that true by construction
    instead of relying on every writer happening to pass ``str(...)``.
    """

    def test_non_str_values_are_coerced_to_their_stored_form(self):
        """A UUID pk and an int pk hash exactly what the columns store.

        Pre-generalisation only ``user_id`` was coerced; any other future
        writer passing a non-str would hash one value and store another, and
        verify would cry tampering on a row nobody touched.
        """
        from apps.audit.services import _canonical_fields

        payload = uuid.UUID("12345678-1234-5678-1234-567812345678")
        canonical = _canonical_fields(
            {
                "action": "update",
                "entity_type": "registry.patient",
                "entity_id": payload,
                "source": "",
                "reason": None,
                "source_ip": None,
                "user_id": 7,
            }
        )

        assert canonical["entity_id"] == str(payload)
        assert canonical["user_id"] == uuid.UUID(int=7)
        assert canonical["source"] == ""
        assert canonical["reason"] is None
        assert canonical["source_ip"] is None

    def test_omitted_fields_resolve_to_none(self):
        """An omitted kwarg and a stored NULL hash to the same value.

        ``entity_id`` has no NULL default, but the nullable columns do, and a
        writer that omits one must not disagree with the row it wrote.
        """
        from apps.audit.services import _canonical_fields

        canonical = _canonical_fields({"action": "read"})

        assert canonical == {
            "action": "read",
            "entity_id": None,
            "entity_type": None,
            "reason": None,
            "source": None,
            "source_ip": None,
            "user_id": None,
        }
