"""Outbound ABDM sandbox client — ABHA create/verify at the counter (REG-009).

The counter needs to create a new ABHA or verify an existing one while the
patient is at the desk. That is an *outbound* call to the ABDM sandbox, driven
by the ``ABDM_SANDBX_BASE_URL`` environment variable with a per-tenant
``IntegrationAdapter(name="abdm")`` row as the fallback, over ``httpx`` (the
declared-but-unused dependency this module wires).

Sandbox-only by design: :func:`require_sandbox_base_url` refuses any base URL
that is not https on an ``sbx`` hostname, and ``config/settings/base.py`` runs
the same gate at import time, so configuration alone can never point this
client at the production ABDM endpoints.

Endpoint paths are patterned on the ABDM sandbox v1 enrollment API
(``createHealthIdWithPreVerified`` / ``mobile/verifyOtp``) as mirrored by the
community spec at build time. The official sandbox create/verify spec
(endpoint paths, payloads, OTP flow) is still unresolved — see the REG-009
entry under Known gaps in ``docs/traceability.md`` — so these paths are the
documented contract to re-verify when the sandbox spec is confirmed.

Fail-closed contract: a caller with no configured base URL is refused with a
503 before any HTTP is attempted (the views never fake a 200 for a request the
adapter could not make), a non-2xx sandbox response raises
:class:`ABDMRequestError` with the status and body, and a network failure
before any response propagates as ``httpx.TransportError``.
"""
import urllib.parse

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class ABDMRequestError(RuntimeError):
    """A non-2xx sandbox response, carrying the status code and raw body."""

    def __init__(self, status_code: int, body) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(
            f"ABDM sandbox request failed with HTTP {status_code}: {body!r}"
        )


def require_sandbox_base_url(value: str) -> str:
    """Validate an ABDM base URL, returning it without a trailing slash.

    The sandbox gate: https scheme and an ``sbx`` hostname (covers
    ``healthidsbx.abdm.gov.in``). Rejecting anything else here means a
    mis-typed value fails loudly at settings import instead of silently
    directing tenant traffic at the production ABDM endpoint. The predicate
    is deliberately fail-closed: a future *legitimate* sandbox host without
    ``sbx`` in its name would need an explicit operator opt-in here, never a
    silent widening of the gate.
    """
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or "sbx" not in parsed.netloc.lower():
        raise ImproperlyConfigured(
            "ABDM_SANDBX_BASE_URL must be an https URL on an 'sbx' hostname "
            "(sandbox-only gate); got {!r}.".format(value)
        )
    return value.rstrip("/")


def resolve_sandbox_base_url(tenant_id=None) -> str:
    """The sandbox root a tenant may use, or ``""`` when none is configured.

    The environment value wins; an active ``IntegrationAdapter(name="abdm")``
    row for the tenant is the per-tenant fallback. An adapter-supplied URL
    passes through the same sandbox gate, so one tenant cannot silently point
    the client at a non-sandbox endpoint.
    """
    url = settings.ABDM_SANDBX_BASE_URL or ""
    if not url and tenant_id is not None:
        from apps.integration.models import IntegrationAdapter

        adapter = (
            IntegrationAdapter.objects.filter(
                tenant_id=tenant_id, name="abdm", active=True
            )
            .order_by("-created_at")
            .first()
        )
        if adapter is not None and isinstance(adapter.config, dict):
            #: The documented per-tenant config key: the sandbox root, e.g.
            #: ``{"base_url": "https://healthidsbx.abdm.gov.in/api/v1"}``.
            url = str(adapter.config.get("base_url") or "").strip()
    return require_sandbox_base_url(url) if url else ""


class ABDMClient:
    """Small outbound client for the ABDM sandbox ABHA enrollment APIs.

    ``transport`` is injectable (``httpx.MockTransport`` in tests) so the
    request the client builds is pinned without touching the network.
    """

    def __init__(self, base_url: str, *, transport=None, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        if transport is not None:
            self._client = httpx.Client(transport=transport, timeout=timeout)
        else:
            self._client = httpx.Client(timeout=timeout)

    def _post(self, path: str, payload: dict) -> dict:
        """POST ``path`` under the base URL, returning the parsed JSON body.

        A non-2xx response raises :class:`ABDMRequestError`; a failure before
        any response propagates as ``httpx.TransportError``. A 2xx whose body
        is not JSON (a WAF login page, a proxy error page) also raises
        :class:`ABDMRequestError` with that 2xx status, so the caller can
        answer a structured failure instead of letting a raw
        ``json.JSONDecodeError`` escape as an unstructured 500.
        """
        response = self._client.post(f"{self._base}{path}", json=payload)
        if response.status_code < 200 or response.status_code >= 300:
            #: The sandbox errors JSON (``{"details": [...]}``); carry the
            #: parsed body so the 503 re-shaping in the views and the test
            #: assertions see the same structure, falling back to the raw text
            #: for a body that is not JSON at all.
            try:
                body = response.json()
            except ValueError:
                body = response.text
            raise ABDMRequestError(response.status_code, body)
        try:
            return response.json()
        except ValueError:
            #: Same fallback discipline as the error path on a 2xx: a non-JSON
            #: success body is a malformed sandbox response (WAF/proxy page),
            #: so it raises with its 2xx status and the raw text. The views
            #: map any status outside 4xx/5xx to a structured 502
            #: ``ABDM_REQUEST_FAILED`` body — never an unstructured 500.
            raise ABDMRequestError(response.status_code, response.text)

    def create_abha(self, payload: dict) -> dict:
        """Create a new ABHA (REG-009); the payload is the sandbox spec's.

        The create payload (Aadhaar OTP, mobile OTP or pre-verified flow) is
        passed through verbatim because the sandbox spec is unresolved; the
        call shape is pinned by tests/integration/test_abha_services.py.
        """
        return self._post("/enrollment/createHealthIdWithPreVerified/", payload)

    def verify_abha(self, abha: str, otp: str) -> dict:
        """Verify an existing ABHA with the mobile OTP the patient received."""
        return self._post(
            "/enrollment/mobile/verifyOtp/", {"healthId": abha, "otp": otp}
        )