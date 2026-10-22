"""Shared fixtures for the integration suite.

The ABDM Scan and Share callback is authenticated by a real HMAC now
(ABD-005), so any test that posts a callback has to sign the exact bytes it
sends — the view recomputes the digest over the raw body it receives and a
presence-only header authenticates nothing. Signing lives once here rather
than being copied into each test file, and ``test_abdm_callback.py`` remains
the file that pins the gate's behaviour.
"""
import hashlib
import hmac
import json

import pytest
from django.conf import settings

CALLBACK_URL = "/api/v1/abdm-callbacks/"


@pytest.fixture
def post_signed_callback():
    """Post an HMAC-signed ABDM callback, the way the gateway does.

    Returns a function ``(client, payload, url=CALLBACK_URL) -> response``.
    The payload is serialized exactly once and *those* bytes are signed:
    serializing again (or letting the client re-encode a dict) can reorder
    keys or change the separators, and a body whose bytes differ from the ones
    signed is refused as tampered.
    """

    def _post(client, payload, url=CALLBACK_URL):
        body = json.dumps(payload).encode()
        signature = hmac.new(
            settings.ABDM_CLIENT_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        return client.post(
            url, body, content_type="application/json", HTTP_X_ABDM_SIGNATURE=signature
        )

    return _post
