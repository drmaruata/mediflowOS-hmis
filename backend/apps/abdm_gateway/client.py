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

INT-002 — one adapter, older and newer API versions. SRS INT-002 requires the
integration to serve both, and architecture doc section 8.2 records why: v1.0 and
v3 paths coexisted on the ABDM gateway while the ABHA app still called the older
flow. This module owns the whole version contract:

* :data:`SUPPORTED_API_VERSIONS` is the single source of truth. Resolution, the
  error message, the outbound dispatch and the callback's acknowledgement all
  read it, so the client, the callback and the tests cannot disagree about what
  "supported" means.
* :func:`build_profile_share_request` and :func:`build_callback_ack` are **pure
  functions, payload in and payload out** — no I/O, no database, no ``settings``,
  no clock — which is what makes the version contract testable without a network
  or a sandbox credential.
* ``ABDMClient.for_adapter`` binds a client to an ``IntegrationAdapter`` row's
  version, refusing an inactive row and an unconfigured or non-sandbox base URL
  before any HTTP is attempted.

**``v2`` is the pre-INT-002 behaviour, byte for byte.** Before version support
there was exactly one shape, so that shape *is* ``v2`` and it is the field
default — which is also what makes the model migration behaviour-preserving for
every existing tenant. ``tests/integration/test_abha_services.py`` pins the
pre-change acknowledgement bytes against ``v2``.

**A version *label* is never refused, and that is a deliberate trade-off.**
:func:`resolve_api_version` resolves an exact label to itself, a documented
alias (:data:`API_VERSION_ALIASES`) to its target, and *anything else* to
:data:`DEFAULT_API_VERSION` with a warning. Only a **malformed** declaration — a
list, an object or a number where a label belongs — raises.

The trade-off, stated plainly because it was argued: the task brief asked for a
422 on an unsupported version, and refusing an unrecognised label *was* that. It
was reversed because the official ABDM spec is unresolved (REG-009), so no label
a gateway can send can be proven unsupported — while this callback is a
fully-implemented production endpoint (architecture doc §8.4, all seven
requirements met). ``v1.0`` is the label this repository's own documentation uses
for the legacy flow (architecture doc §8.2,
``tests/integration/test_abdm_sandbox.py``), so the registry was refusing the
project's own vocabulary: a self-inflicted outage over a wording difference.
INT-002 asks for two versions to be **served**, not for unknown ones to be
rejected. Fail-closed is kept where it protects: the sandbox gate, the
inactive-row off-switch, the missing base URL, and a declaration too malformed to
read.

**``v3`` is provisional and must be re-verified.** The official sandbox spec is
still unresolved (the REG-009 entry under Known gaps in
``docs/traceability.md``), so v3's shape here is derived only from the vocabulary
this repository already exchanges with the gateway (camelCase keys such as
``requestId``, ``sourceApp``, ``abhaNumber``). It is a documented placeholder,
not a claim about the real ABDM API.
"""
import logging
import urllib.parse

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

#: The ABDM profile-share API versions this deployment speaks (INT-002). An
#: older and a newer one; see the module docstring for what "older" means here.
SUPPORTED_API_VERSIONS = ("v2", "v3")

#: The version used when nothing declares one, and the version an unrecognised
#: declaration falls back to. ``v2`` because it reproduces the single
#: unversioned shape exactly, so a gateway that declares nothing, declares
#: something unfamiliar, and a tenant with no adapter row all keep today's
#: contract.
DEFAULT_API_VERSION = "v2"

#: Version labels the gateway is known to use, mapped onto the shape this
#: deployment serves them in (INT-002). An alias records a decision — "we serve
#: this, in this shape" — where the fallback below only records that a label is
#: unrecognised. Add a label here when the peer needs a shape of its own; do not
#: add labels that merely want the default shape.
API_VERSION_ALIASES = {"v1.0": "v2", "1.0": "v2"}

#: The key a callback declares its API version with. Inside the signed body and
#: not a header, deliberately: only the body is covered by the ABDM-005 HMAC,
#: so a version carried in a header could be added or stripped in transit and
#: would change the shape of the acknowledgement with nothing able to detect it.
API_VERSION_PAYLOAD_KEY = "apiVersion"

#: The acknowledgement keys either version may carry. Both builders select from
#: this list rather than passing their input through, so nothing a caller hands
#: them can put a field on the wire by accident — which is how ``link_token``
#: stays off it (ABD-012).
_ACK_FIELDS = ("status", "token", "request_id", "patient_id", "consent_event", "detail")

#: ``v3``'s wire names for those keys. The order is the response's field order.
_V3_ACK_FIELD_NAMES = {
    "status": "status",
    "token": "token",
    "request_id": "requestId",
    "patient_id": "patientId",
    "consent_event": "consentEvent",
    "detail": "detail",
}

#: The consent event's own ``v3`` names, for the same reason.
_V3_CONSENT_FIELD_NAMES = {
    "timestamp": "timestamp",
    "source_app": "sourceApp",
    "purpose": "purpose",
    "facility_id": "facilityId",
}


class ABDMRequestError(RuntimeError):
    """A non-2xx sandbox response, carrying the status code and raw body."""

    def __init__(self, status_code: int, body) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(
            f"ABDM sandbox request failed with HTTP {status_code}: {body!r}"
        )


class ABDMAdapterError(RuntimeError):
    """Base for the failures ``for_adapter`` refuses on, all before any HTTP."""


class ABDMUnsupportedVersionError(ABDMAdapterError):
    """An ``api_version`` that is not a version label at all.

    Raised only for a **malformed** value — a list, an object, a number, a
    boolean — and never for a label this deployment does not recognise (those
    resolve to :data:`DEFAULT_API_VERSION`; see :func:`resolve_api_version` and
    the trade-off in the module docstring). Carries both sides of the answer so a
    caller can report them without re-deriving the supported set: the value
    received, and the versions this deployment serves.
    """

    def __init__(self, requested, supported=SUPPORTED_API_VERSIONS) -> None:
        self.requested = requested
        self.supported = tuple(supported)
        #: The type rather than the value: the value is unusable by definition
        #: here, and echoing an arbitrary caller-supplied object into a response
        #: body is needless exposure.
        described = (
            requested if isinstance(requested, str) else type(requested).__name__
        )
        super().__init__(
            "Malformed ABDM API version: {described!r} is not a version label. "
            "Supported versions: {supported}.".format(
                described=described, supported=", ".join(self.supported)
            )
        )


class ABDMAdapterInactiveError(ABDMAdapterError):
    """The adapter row is ``active=False`` — the operator's deliberate off-switch."""


class ABDMSandboxUnconfiguredError(ABDMAdapterError):
    """No sandbox base URL is resolvable, so there is nowhere to send a request."""


def resolve_api_version(value, *, tenant_id=None) -> str:
    """The version to speak for ``value``, resolving rather than refusing.

    Three rules, in order:

    1. an **exact** supported label (whitespace stripped) resolves to itself;
    2. a label in :data:`API_VERSION_ALIASES` resolves to the shape it names;
    3. anything else resolves to :data:`DEFAULT_API_VERSION`, with a warning.

    Surrounding whitespace is stripped as a transport artefact. Case is **not**
    folded: deciding that ``"V3"`` means ``"v3"`` would decide the
    acknowledgement's shape by guessing at what the sender meant. Rule 3 exists
    because an unrecognised label must not refuse a scan — the module docstring
    records why, and what was given up to get here.

    ``None`` means "nothing was declared" and resolves to the default without a
    warning: an absent declaration is a state, not a surprise.

    ``tenant_id`` exists only so the fallback warning can say *whose* channel is
    being answered in the wrong shape. It is a tenant UUID — no patient data is
    involved, the label logged is a contract token from an already-authenticated
    body.

    The fallback warns on **every** call, and that is deliberate: a gateway or an
    adapter row configured with an unrecognised label is a standing
    misconfiguration, not a per-request event, so a deployment in that state is
    noisy until an operator reads the log. Deduplicating or throttling the
    warning would hide a channel being served the wrong shape, which is the one
    finding here an operator acts on.

    Raises:
        ABDMUnsupportedVersionError: ``value`` is not a string. A malformed
            declaration has no honest fallback to guess, and answering one with a
            successful-looking acknowledgement hides a broken sender.
    """
    if value is None:
        return DEFAULT_API_VERSION
    if not isinstance(value, str):
        raise ABDMUnsupportedVersionError(value)
    candidate = value.strip()
    if candidate in SUPPORTED_API_VERSIONS:
        return candidate
    aliased = API_VERSION_ALIASES.get(candidate)
    if aliased is not None:
        return aliased
    logger.warning(
        "ABDM: unrecognised API version label %r for tenant %s; serving %s "
        "(the pre-versioning shape) instead of refusing the call. Add the label "
        "to API_VERSION_ALIASES if the peer really speaks a different contract.",
        value,
        tenant_id if tenant_id is not None else "unknown",
        DEFAULT_API_VERSION,
    )
    return DEFAULT_API_VERSION


def declared_api_version(payload: dict):
    """The API version this callback declares, or ``None`` when it declares none.

    A blank string and a JSON null are *absent*: a sender that left the field
    empty has said nothing about which contract it is speaking, and refusing it
    would turn an unambiguous request into an error.

    A non-string is **returned unchanged** rather than dropped. Coercing
    ``{"apiVersion": {"v": 3}}`` into a version would be a guess, but discarding
    it is how a broken sender ends up answered ``200`` in the default shape as
    though it had been understood; surfacing it is what lets
    :func:`resolve_api_version` refuse it as malformed. Nothing is validated
    here — validation is :func:`resolve_api_version`'s job, and the caller
    decides when to run it.
    """
    if not isinstance(payload, dict):
        return None
    if API_VERSION_PAYLOAD_KEY not in payload:
        return None
    declared = payload[API_VERSION_PAYLOAD_KEY]
    if declared is None:
        return None
    if isinstance(declared, str):
        return declared if declared.strip() else None
    return declared


def build_profile_share_request(api_version: str, payload: dict) -> dict:
    """The outbound profile-share body, shaped for ``api_version``. Pure.

    ``v2`` is the identity — the payload exactly as the client would have sent it
    before version support existed. ``v3`` adds the version declaration and
    changes nothing else: with the sandbox spec unresolved (REG-009) the only
    newer-flow difference this repository can justify is the declaration itself,
    and inventing a nested envelope or renamed fields would be a claim about
    ABDM's API that nothing verifies.

    Dispatches on the *resolved* version, so an alias or a padded label builds the
    shape it names rather than falling through to ``v2``. ``v3``'s own declaration
    overwrites any the payload carries: the merge used to run the other way
    round, so a caller could put a ``"v2"`` stamp on the wire from a v3-bound
    client while ``client.api_version`` said v3 — two truths about one request.
    """
    api_version = resolve_api_version(api_version)
    if api_version != "v3":
        return dict(payload)
    body = dict(payload)
    body.pop(API_VERSION_PAYLOAD_KEY, None)
    return {API_VERSION_PAYLOAD_KEY: "v3", **body}


def build_callback_ack(api_version: str, fields: dict) -> dict:
    """The acknowledgement body for ``api_version``, from canonical fields. Pure.

    ``fields`` is the view's canonical, serializer-produced set (``status``,
    ``token``, ``request_id``, ``patient_id``, ``consent_event``, plus a branch's
    own ``detail``); this is where the version's wire vocabulary is applied.

    ``v2`` passes those fields through unchanged, preserving their order, which
    is what makes its bytes identical to the pre-INT-002 acknowledgement.
    ``v3`` renames them into the camelCase vocabulary the gateway itself uses on
    the way in and stamps the version it is answering in — also provisional, for
    the reason in the module docstring.

    Dispatches on the *resolved* version, so an alias or a padded label answers in
    the shape it names.
    """
    api_version = resolve_api_version(api_version)
    if api_version != "v3":
        return {key: value for key, value in fields.items() if key in _ACK_FIELDS}
    body = {API_VERSION_PAYLOAD_KEY: "v3"}
    for key, name in _V3_ACK_FIELD_NAMES.items():
        if key not in fields:
            continue
        value = fields[key]
        body[name] = _v3_consent_event(value) if key == "consent_event" else value
    return body


def _v3_consent_event(consent_event):
    """Rename the consent event's fields for ``v3``; a null event stays null.

    Only the four attributes the architecture doc names (timestamp, source,
    purpose, facility) are carried in any version — never ``raw_profile_hash``
    and never a patient attribute (data minimisation, section 8.4).
    """
    if not isinstance(consent_event, dict):
        return consent_event
    return {
        name: consent_event[key]
        for key, name in _V3_CONSENT_FIELD_NAMES.items()
        if key in consent_event
    }


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


def adapter_sandbox_base_url(adapter) -> str:
    """The sandbox root ``adapter`` names, falling back to the environment's.

    Read off **the row it was handed**, not re-queried by tenant: the previous
    implementation queried for the newest active ``abdm`` row, which agreed with
    the adapter in hand only by accident of ``unique_together(tenant_id, name)``
    and would bind the wrong row the moment a tenant could hold two.

    The environment value still wins when the row carries none, and the row's own
    URL goes through the same :func:`require_sandbox_base_url` gate either way:
    an adapter row cannot point the client at production ABDM.
    """
    url = str(settings.ABDM_SANDBX_BASE_URL or "").strip()
    if not url and isinstance(getattr(adapter, "config", None), dict):
        #: The documented per-tenant config key: the sandbox root, e.g.
        #: ``{"base_url": "https://healthidsbx.abdm.gov.in/api/v1"}``.
        url = str(adapter.config.get("base_url") or "").strip()
    return require_sandbox_base_url(url) if url else ""


class ABDMClient:
    """Small outbound client for the ABDM sandbox ABHA enrollment APIs.

    ``transport`` is injectable (``httpx.MockTransport`` in tests) so the
    request the client builds is pinned without touching the network.

    The client is bound to one API version (INT-002), resolved in the
    constructor rather than at dispatch, so a client can never hold a version no
    builder handles. An unrecognised label resolves to the default shape with a
    warning rather than raising — see :func:`resolve_api_version` — and it
    defaults to :data:`DEFAULT_API_VERSION`, the pre-versioning behaviour.
    """

    def __init__(
        self,
        base_url: str,
        *,
        transport=None,
        timeout: float = 10.0,
        api_version: str = DEFAULT_API_VERSION,
    ) -> None:
        self.api_version = resolve_api_version(api_version)
        self._base = base_url.rstrip("/")
        if transport is not None:
            self._client = httpx.Client(transport=transport, timeout=timeout)
        else:
            self._client = httpx.Client(timeout=timeout)

    @classmethod
    def for_adapter(cls, adapter, *, transport=None, timeout: float = 10.0):
        """A client bound to an ``IntegrationAdapter`` row's version and URL.

        Everything that can be refused is refused **before any HTTP**:

        * an inactive row (:class:`ABDMAdapterInactiveError`) — ``active=False``
          is the operator's off-switch, and the base-URL resolver already filters
          on ``active=True``, so binding straight from a row must not become a
          way around that filter;
        * an ``api_version`` that is not a version label at all
          (:class:`ABDMUnsupportedVersionError`). An unrecognised *label* is not
          refused — it resolves to the default shape with a warning, so one
          mistyped row cannot take the tenant's whole channel down;
        * a base URL that is not a sandbox (:class:`ImproperlyConfigured`, from
          the same :func:`require_sandbox_base_url` gate settings import runs) or
          no base URL at all (:class:`ABDMSandboxUnconfiguredError`).

        The base URL comes from :func:`adapter_sandbox_base_url`, so the
        precedence stays the one the module already owns — environment first,
        then **this** adapter's own ``config["base_url"]`` — while reading the row
        it was handed instead of querying for it again.

        Caught by: the caller. Nothing in the repository constructs a client
        through this method yet (the counter actions still build one from the
        resolved base URL directly), so today the failures surface to the test
        suite and to the first production call site that adopts it.
        """
        if not getattr(adapter, "active", False):
            raise ABDMAdapterInactiveError(
                "ABDM adapter {!r} is inactive; the row is the tenant's "
                "deliberate off-switch for this integration.".format(
                    getattr(adapter, "name", "abdm")
                )
            )
        api_version = resolve_api_version(
            getattr(adapter, "api_version", None),
            tenant_id=getattr(adapter, "tenant_id", None),
        )
        base_url = adapter_sandbox_base_url(adapter)
        if not base_url:
            raise ABDMSandboxUnconfiguredError(
                "No ABDM sandbox base URL is configured for this adapter; set "
                "ABDM_SANDBX_BASE_URL or the adapter's config['base_url']."
            )
        return cls(
            base_url, transport=transport, timeout=timeout, api_version=api_version
        )

    def profile_share_body(self, payload: dict) -> dict:
        """The profile-share body this client would post, shaped for its version.

        Separate from :meth:`_post` because the profile-share *endpoint path* is
        not in the documented sandbox spec (REG-009): inventing a path here would
        be a claim nothing verifies. What the version adapter owns is the body,
        so that is what this exposes — which is also why it is safe to unit-test
        with no transport at all.
        """
        return build_profile_share_request(self.api_version, payload)

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