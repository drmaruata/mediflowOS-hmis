"""Field-encryption primitives for REG-008 (patient identifiers at rest).

``abha_number``, ``abha_address`` and ``contact.mobile`` are AES-256-GCM token
values in the database. This module is deliberately free of any Django import:
the ORM layer, the ABDM gateway, and the ``0010`` data migration all call the
same functions, so the ciphertext they produce and accept is interchangeable.

Design points, each pinned by tests/unit/test_crypto.py:

- Tokens are self-contained ``v1:<iv>:<ciphertext>`` strings (base64). The IV
  travels inside the token, so nothing outside the stored value is needed to
  open it, and authentication is real: a wrong key or any tampering raises
  ``InvalidTag`` loudly rather than returning garbage.
- ``derive_keys`` expands the master passphrase with PBKDF2-HMAC-SHA256 into
  two independent 32-byte keys (AES + HMAC), domain-separated by salt suffix.
  The salt is a fixed application constant: the derived keys must be stable
  across restarts so an already-encrypted database keeps decrypting. The salt
  is public — it only separates this application's key stream from other
  PBKDF2 users, it is not a secret.
- ``search_index`` is a keyed HMAC-SHA256 digest, not a bare hash. Mobiles and
  ABHA numbers are low-entropy; an unkeyed hash in the index column would turn
  it into an offline dictionary-attack oracle for anyone with a copy of the
  table. The key is what makes the column usable for exact lookup but useless
  to an attacker.

Key material (both derived keys and the master passphrase) must never be
logged.
"""
import base64
import binascii
import hashlib
import hmac
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Every stored token starts with this literal; it doubles as the "already
#: encrypted" marker that the model's write path checks to avoid re-encrypting
#: a value it just read back.
TOKEN_PREFIX = "v1:"

#: Salt prefixes for the two PBKDF2 derivations. Distinct suffixes give the
#: AES and HMAC keys independent key streams (domain separation): recovering
#: the AES key must not also unlock the search-index oracle, and vice versa.
_SALT = b"mediflowOS-hmis:REG-008:field-encryption:v1"
_AES_SALT = _SALT + b":aes"
_HMAC_SALT = _SALT + b":hmac"

#: OWASP's 2023 recommendation for PBKDF2-HMAC-SHA256. The derivation is
#: memoised per passphrase, so this cost is paid once per process, not once per
#: field write.
_PBKDF2_ITERATIONS = 600_000


class TokenFormatError(ValueError):
    """The stored value is not a well-formed ``v1:`` envelope."""


@lru_cache(maxsize=None)
def derive_keys(passphrase: str) -> tuple[bytes, bytes]:
    """Expand ``passphrase`` into the (aes_key, hmac_key) pair, both 32 bytes.

    Deterministic for a given passphrase: the two keys must be identical after
    every restart or an encrypted database becomes undecryptable. An empty
    passphrase refuses to derive — encrypting under a missing master key must
    never silently happen.
    """
    if not passphrase:
        raise ValueError(
            "Refusing to derive keys from an empty passphrase: field encryption "
            "must never run under a missing master key."
        )
    password = passphrase.encode("utf-8")
    aes_key = hashlib.pbkdf2_hmac(
        "sha256", password, _AES_SALT, _PBKDF2_ITERATIONS, dklen=32
    )
    hmac_key = hashlib.pbkdf2_hmac(
        "sha256", password, _HMAC_SALT, _PBKDF2_ITERATIONS, dklen=32
    )
    return aes_key, hmac_key


def encrypt(plaintext: str, *, key: bytes) -> str:
    """Seal ``plaintext`` into a self-contained ``v1:<iv>:<ciphertext>`` token.

    A fresh 12-byte random IV is generated per call — reusing a nonce under
    the same key is catastrophically fatal for AES-GCM, so the IV is never
    derived from the plaintext (same plaintext must produce different tokens).
    """
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return (
        f"{TOKEN_PREFIX}"
        f"{base64.b64encode(nonce).decode('ascii')}:"
        f"{base64.b64encode(ciphertext).decode('ascii')}"
    )


def decrypt(token: str, *, key: bytes) -> str:
    """Open a ``v1:`` token back to its plaintext.

    Malformed envelopes raise :class:`TokenFormatError` (a corrupt or foreign
    value is called out, never guessed at); a well-formed token that fails
    authentication raises ``cryptography.exceptions.InvalidTag`` — wrong key,
    tampered ciphertext, or a truncated tag all fail the same loud way.
    """
    parts = token.split(":", 2)
    if len(parts) != 3:
        raise TokenFormatError(f"Not a v1 token: {token!r}")
    version, iv_b64, ct_b64 = parts
    if version != "v1":
        raise TokenFormatError(f"Unknown token version: {version!r}")
    try:
        nonce = base64.b64decode(iv_b64, validate=True)
        ciphertext = base64.b64decode(ct_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TokenFormatError("Token carries invalid base64 data.") from exc
    if len(nonce) != 12:
        raise TokenFormatError("Token carries an invalid IV.")
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def search_index(plaintext: str, *, key: bytes) -> str:
    """Deterministic keyed digest of ``plaintext`` for exact index lookups.

    The digest is stable (same plaintext, same key, same value) so REG-002/
    REG-003 can match without decrypting, but keyed — a bare hash would let
    the low-entropy mobile/ABHA values be recovered by offline dictionary
    attack against the index column alone.
    """
    return hmac.new(key, plaintext.encode("utf-8"), hashlib.sha256).hexdigest()