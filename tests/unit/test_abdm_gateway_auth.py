"""Unit tests for the ABDM callback's signature gate (ABD-005).

``tests/integration/test_abdm_callback.py`` pins the gate end to end through
the router, which is where most of the behaviour belongs. These tests cover
what an integration test cannot reach without changing the shared suite
settings: the environment asymmetry of an *unset* shared secret. The sandbox
hands out no secret, so ``ABDM_CLIENT_SECRET`` empty is a real state the code
has to answer for, and the answer differs by ``DEBUG`` — that difference is
the whole test.

Both values are read from ``settings`` at call time rather than captured at
import, which is what lets ``override_settings`` flip them here.
"""
import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.abdm_gateway.views import ABHACallbackViewSet

SECRET = "unit-test-shared-secret"
PAYLOAD = b'{"requestId":"req-1","timestamp":"2026-10-09T00:00:00Z"}'


def _request(body=PAYLOAD, signature=None, **extra):
    """Build a DRF request over the given raw body bytes.

    The bytes are posted verbatim (the factory does not re-encode them) so the
    digest under test is the one the wire would carry.
    """
    if signature is not None:
        extra.setdefault("HTTP_X_ABDM_SIGNATURE", signature)
    factory = APIRequestFactory()
    return Request(
        factory.post(
            "/api/v1/abdm-callbacks/", body, content_type="application/json", **extra
        )
    )


def _sign(body, secret=SECRET):
    """Return the header value the gateway would send for ``body``."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.unit
class TestSignatureVerification:
    """The happy path is a real HMAC over the exact bytes received."""

    def test_valid_signature_is_accepted(self):
        request = _request(signature=_sign(PAYLOAD))

        with override_settings(ABDM_CLIENT_SECRET=SECRET):
            assert ABHACallbackViewSet()._authenticate_call(request) is True

    def test_wrong_secret_is_refused(self):
        """A digest from another secret must not authenticate (ABD-005)."""
        request = _request(signature=_sign(PAYLOAD, secret="attacker-secret"))

        with override_settings(ABDM_CLIENT_SECRET=SECRET):
            assert ABHACallbackViewSet()._authenticate_call(request) is False

    def test_signature_covers_the_raw_body_not_a_reparsed_payload(self):
        """Re-serialising the parsed JSON must not produce an accepted digest.

        The old presence-only check had nothing to keep honest here. Signing
        the raw bytes is what makes the order and spacing of the body
        significant: a digest computed over the re-dumped JSON is refused, so
        a caller cannot rewrite the payload and pass the original signature
        off as its own.
        """
        reparsed = json.dumps(json.loads(PAYLOAD), indent=2).encode()
        assert reparsed != PAYLOAD  # the re-serialization really is different
        request = _request(signature=_sign(reparsed))

        with override_settings(ABDM_CLIENT_SECRET=SECRET):
            assert ABHACallbackViewSet()._authenticate_call(request) is False

    def test_missing_signature_header_is_refused(self):
        """No credential is refused even when a secret is configured."""
        request = _request()

        with override_settings(ABDM_CLIENT_SECRET=SECRET):
            assert ABHACallbackViewSet()._authenticate_call(request) is False

    @pytest.mark.parametrize("header_value", ["", "   "])
    def test_blank_signature_header_is_refused(self, header_value):
        """Whitespace is an absent credential, not a valid one."""
        request = _request(signature=header_value)

        with override_settings(ABDM_CLIENT_SECRET=SECRET):
            assert ABHACallbackViewSet()._authenticate_call(request) is False

    def test_non_ascii_signature_is_refused_not_raised(self):
        """A header with non-ASCII bytes must fail the check, not the request.

        The header value is attacker-controlled and arrives decoded as ISO
        8859-1; comparing it as ``str`` raises ``TypeError`` for a value such
        as this one, which would surface as a 500 instead of a 401.
        """
        request = _request(signature="nöt-the-digest")

        with override_settings(ABDM_CLIENT_SECRET=SECRET):
            assert ABHACallbackViewSet()._authenticate_call(request) is False


@pytest.mark.unit
class TestUnsetSecretAsymmetry:
    """An unset shared secret behaves differently in and out of DEBUG.

    The sandbox issues no secret, so this is not a hypothetical: what differs
    is whether a developer running locally can exercise the endpoint at all.
    Failing closed everywhere would make the local flow unusable; failing open
    everywhere would accept unsigned writes in production.
    """

    @override_settings(ABDM_CLIENT_SECRET="", DEBUG=True)
    def test_debug_accepts_with_a_warning(self, caplog):
        """DEBUG is the documented fail-open mode, and it says so in the log.

        The warning names the mechanism so the acceptance is never silent; it
        must not carry the secret (there is none) or any patient data.
        """
        request = _request(signature=_sign(PAYLOAD))

        with caplog.at_level("WARNING", logger="apps.abdm_gateway.views"):
            assert ABHACallbackViewSet()._authenticate_call(request) is True

        assert "ABDM_CLIENT_SECRET" in caplog.text

    @override_settings(ABDM_CLIENT_SECRET="", DEBUG=True)
    def test_debug_still_refuses_a_missing_credential(self):
        """DEBUG excuses an unverifiable signature, never an absent one."""
        request = _request()

        assert ABHACallbackViewSet()._authenticate_call(request) is False

    @override_settings(ABDM_CLIENT_SECRET="", DEBUG=False)
    def test_outside_debug_it_fails_closed(self, caplog):
        """Production must refuse when there is nothing to verify against."""
        request = _request(signature=_sign(PAYLOAD))

        with caplog.at_level("WARNING", logger="apps.abdm_gateway.views"):
            assert ABHACallbackViewSet()._authenticate_call(request) is False

        assert "ABDM_CLIENT_SECRET" in caplog.text


@pytest.mark.unit
class TestTimestampWindow:
    """ABD-007: the tolerance window is a setting, not a literal."""

    def test_configured_window_is_used(self):
        """A narrowed window rejects a timestamp the default one accepts.

        Both halves matter: the first pins that a 30-second drift is fine
        inside the ABDM window, the second that the value is read from
        settings rather than hardcoded at 300.
        """
        payload = {"timestamp": (timezone.now() - timedelta(seconds=30)).isoformat()}

        assert ABHACallbackViewSet()._validate_timestamp(payload) is True
        with override_settings(ABDM_MAX_SKEW_SECONDS=10):
            assert ABHACallbackViewSet()._validate_timestamp(payload) is False

    def test_garbage_configured_window_falls_back_to_the_default(self, monkeypatch):
        """A non-numeric or non-positive value must not widen the window.

        ``ABDM_MAX_SKEW_SECONDS=0`` would accept any timestamp, and a
        non-numeric one would raise at import; the guard in base.py keeps the
        documented 5-minute default instead. Re-imported from source rather
        than mocked so the guard itself is what is exercised.
        """
        import importlib
        import sys

        monkeypatch.setenv("ABDM_MAX_SKEW_SECONDS", "0")
        sys.modules.pop("config.settings.base", None)

        module = importlib.import_module("config.settings.base")

        assert module.ABDM_MAX_SKEW_SECONDS == 300
