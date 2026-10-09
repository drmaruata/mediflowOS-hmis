"""REG-008 crypto primitives: AES-GCM field encryption plus keyed HMAC search index.

The primitives in ``common.crypto`` are pure Python (no Django import) so the
same code is usable from the ORM layer, the ABDM gateway, and the data
migration. These tests pin the *contract* independent of the model layer:

- every stored value is a self-contained ``v1:<iv>:<ciphertext>`` token,
- authentication is real (tampering or a wrong key raises, never silently
  returns garbage),
- the search index is deterministic, keyed, and carries the low-entropy
  mobile/ABHA values that plain hashing would expose to offline attacks.
"""
import base64

import pytest
from cryptography.exceptions import InvalidTag

from common.crypto import (
    TOKEN_PREFIX,
    TokenFormatError,
    decrypt,
    derive_keys,
    encrypt,
    search_index,
)

pytestmark = pytest.mark.unit

PASSPHRASE = "kepi-12-unit-passphrase"
AES_KEY, HMAC_KEY = derive_keys(PASSPHRASE)
OTHER_AES_KEY, OTHER_HMAC_KEY = derive_keys("kepi-12-other-passphrase")


def _tamper(token):
    """Flip one bit in the ciphertext of a valid token, keeping its shape."""
    _, iv_b64, ct_b64 = token.split(":", 2)
    ct = bytearray(base64.b64decode(ct_b64))
    ct[-1] ^= 0xFF
    # TOKEN_PREFIX already carries the trailing colon ("v1:"), so the envelope
    # is joined with one colon, not two — a double colon would empty the IV and
    # turn the tampered token into a *malformed* one (TokenFormatError), which
    # is a different failure than the tamper contract pins (InvalidTag).
    return f"{TOKEN_PREFIX}{iv_b64}:{base64.b64encode(bytes(ct)).decode()}"


# --- round trip ----------------------------------------------------------------

def test_round_trip():
    assert decrypt(encrypt("9876543210", key=AES_KEY), key=AES_KEY) == "9876543210"


def test_round_trip_unicode_and_empty():
    assert decrypt(encrypt("नाम", key=AES_KEY), key=AES_KEY) == "नाम"
    assert decrypt(encrypt("", key=AES_KEY), key=AES_KEY) == ""


def test_tokens_are_versioned_and_self_contained():
    token = encrypt("9876543210", key=AES_KEY)
    assert token.startswith(TOKEN_PREFIX)
    # The IV travels inside the token: nothing outside the stored value is
    # needed to decrypt it.
    assert decrypt(token, key=AES_KEY) == "9876543210"


def test_same_plaintext_encrypts_differently_but_both_decrypt():
    first = encrypt("9876543210", key=AES_KEY)
    second = encrypt("9876543210", key=AES_KEY)
    assert first != second
    assert decrypt(first, key=AES_KEY) == "9876543210"
    assert decrypt(second, key=AES_KEY) == "9876543210"


# --- authentication failures must be loud --------------------------------------

def test_wrong_key_fails_authentication():
    token = encrypt("9876543210", key=AES_KEY)
    with pytest.raises(InvalidTag):
        decrypt(token, key=OTHER_AES_KEY)


def test_tampered_ciphertext_fails_authentication():
    with pytest.raises(InvalidTag):
        decrypt(_tamper(encrypt("9876543210", key=AES_KEY)), key=AES_KEY)


def test_malformed_token_is_rejected():
    for bad in ("", "plaintext", TOKEN_PREFIX, f"{TOKEN_PREFIX}::", f"{TOKEN_PREFIX}:not-base64"):
        with pytest.raises(TokenFormatError):
            decrypt(bad, key=AES_KEY)


def test_unknown_version_is_rejected():
    with pytest.raises(TokenFormatError):
        decrypt("v2:aaaa:bbbb", key=AES_KEY)


# --- deterministic search index ------------------------------------------------

def test_search_index_is_deterministic():
    assert search_index("9876543210", key=HMAC_KEY) == search_index(
        "9876543210", key=HMAC_KEY
    )


def test_search_index_differs_between_plaintexts():
    assert search_index("9876543210", key=HMAC_KEY) != search_index(
        "9000000000", key=HMAC_KEY
    )


def test_search_index_is_keyed():
    """A keyed MAC, not a bare hash.

    Mobiles and ABHA numbers are low-entropy: without the HMAC key an offline
    dictionary attack over the indexed column would recover them from a plain
    hash. The keyed digest is what keeps the index usable for lookup without
    turning it into an oracle.
    """
    assert search_index("9876543210", key=HMAC_KEY) != search_index(
        "9876543210", key=OTHER_HMAC_KEY
    )


def test_search_index_is_hex_digest_length():
    assert len(search_index("x", key=HMAC_KEY)) == 64


# --- key derivation ------------------------------------------------------------

def test_derive_keys_is_deterministic_and_domain_separated():
    aes_a, hmac_a = derive_keys(PASSPHRASE)
    aes_b, hmac_b = derive_keys(PASSPHRASE)
    assert (aes_a, hmac_a) == (aes_b, hmac_b)
    # Encryption and search-index keys are independent: a recovered AES key
    # must not also unlock the index oracle.
    assert aes_a != hmac_a
    assert len(aes_a) == 32
    assert len(hmac_a) == 32


def test_derive_keys_differs_per_passphrase():
    assert derive_keys(PASSPHRASE) != derive_keys("kepi-12-different-passphrase")


def test_empty_passphrase_refuses_to_derive():
    """Encrypting under a missing master key must never silently happen."""
    with pytest.raises(ValueError):
        derive_keys("")