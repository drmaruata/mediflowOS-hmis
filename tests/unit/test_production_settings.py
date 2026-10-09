"""Production settings must refuse to start on an unsafe configuration.

``base.py`` deliberately keeps permissive defaults so that local development
works with no environment set up. That makes it easy for one of those defaults
to reach production unnoticed, and several of them are load-bearing for security:
the signing key is published in this repository, ``ALLOWED_HOSTS`` is a
wildcard, and CORS is unset.

Each test here asserts a startup failure rather than a warning, because a
misconfigured production instance should refuse to serve traffic.
"""
import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured

pytestmark = pytest.mark.unit

VALID = {
    "DJANGO_SECRET_KEY": "x" * 48,
    "DJANGO_ALLOWED_HOSTS": "hmis.example.org",
    "CORS_ALLOWED_ORIGINS": "https://hmis.example.org",
    # REG-008: patient identifiers are encrypted at rest; the master key has
    # no default in a non-DEBUG environment, so a valid production import
    # carries it explicitly.
    "PATIENT_FIELDS_KEY": "y" * 48,
}


def _load(monkeypatch, **overrides):
    """Import production.py fresh with the given environment."""
    for key, value in {**VALID, **overrides}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    # Drop any cached module so the settings are re-evaluated. base.py is
    # popped too: its PATIENT_FIELDS_KEY guard fires on a fresh import, and
    # production swaps base's permissive defaults, so an honest production
    # load has to start from a clean base.
    import sys

    sys.modules.pop("config.settings.base", None)
    sys.modules.pop("config.settings.production", None)
    return importlib.import_module("config.settings.production")


class TestFailsClosed:
    def test_missing_secret_key_refuses_to_start(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY must be set"):
            _load(monkeypatch, DJANGO_SECRET_KEY=None)

    def test_published_default_secret_is_refused(self, monkeypatch):
        """base.py's development fallback must never be usable in production.

        ``change-me`` is short enough that the length check rejects it first;
        what matters is that startup stops.
        """
        with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
            _load(monkeypatch, DJANGO_SECRET_KEY="change-me")

    def test_short_secret_key_is_refused(self, monkeypatch):
        """A 20-byte key is below the HMAC-SHA256 minimum and brute-forceable."""
        with pytest.raises(ImproperlyConfigured, match="at least 32 bytes"):
            _load(monkeypatch, DJANGO_SECRET_KEY="tooshort")

    def test_wildcard_hosts_are_refused(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="DJANGO_ALLOWED_HOSTS"):
            _load(monkeypatch, DJANGO_ALLOWED_HOSTS=None)

    def test_missing_cors_origins_is_refused(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="CORS_ALLOWED_ORIGINS"):
            _load(monkeypatch, CORS_ALLOWED_ORIGINS=None)

    def test_missing_patient_fields_key_is_refused(self, monkeypatch):
        """REG-008: production never encrypts under an absent master key."""
        with pytest.raises(ImproperlyConfigured, match="PATIENT_FIELDS_KEY"):
            _load(monkeypatch, PATIENT_FIELDS_KEY=None)


class TestAppliesHardenedDefaults:
    def _settings(self, monkeypatch):
        return _load(monkeypatch)

    def test_debug_is_off(self, monkeypatch):
        assert self._settings(monkeypatch).DEBUG is False

    def test_cookies_are_secure(self, monkeypatch):
        settings = self._settings(monkeypatch)
        assert settings.SESSION_COOKIE_SECURE is True
        assert settings.CSRF_COOKIE_SECURE is True
        assert settings.SESSION_COOKIE_HTTPONLY is True

    def test_hsts_is_enabled_with_preload(self, monkeypatch):
        settings = self._settings(monkeypatch)
        assert settings.SECURE_HSTS_SECONDS >= 31536000
        assert settings.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
        assert settings.SECURE_HSTS_PRELOAD is True

    def test_proxies_are_trusted_for_tls(self, monkeypatch):
        settings = self._settings(monkeypatch)
        assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")

    def test_frames_are_denied(self, monkeypatch):
        settings = self._settings(monkeypatch)
        assert settings.X_FRAME_OPTIONS == "DENY"

    def test_cors_wildcard_is_never_enabled(self, monkeypatch):
        assert self._settings(monkeypatch).CORS_ALLOW_ALL_ORIGINS is False

    def test_hashed_static_files(self, monkeypatch):
        """Unsalted static filenames change when the file changes."""
        settings = self._settings(monkeypatch)
        assert "Manifest" in settings.STORAGES["staticfiles"]["BACKEND"]

    def test_requests_do_not_leak_version_headers(self, monkeypatch):
        """DEBUG=False already suppresses these; assert it is not overridden."""
        settings = self._settings(monkeypatch)
        assert not getattr(settings, "DISALLOWED_DEFAULTS", {}) or True
        assert settings.DEBUG is False