"""The ABDM API-version registry and its payload builders (INT-002).

INT-002 requires the ABDM integration to serve "older and newer API versions
via an adapter", so the acknowledgement the gateway gets back and the body we
would send out have to be shaped by the version the peer is speaking. This file
pins the two halves of that dispatch:

* :func:`build_profile_share_request` — the outbound body, per version.
* :func:`build_callback_ack` — the acknowledgement, per version.

Both are **pure functions, payload in and payload out**: no I/O, no database, no
``settings``, no clock. That is what makes the version contract testable without
a network, a tenant or a sandbox credential, and it is why they live here as
free functions rather than as methods that reach for a client.

Two invariants are pinned per version rather than once for the module, because
they are exactly the ones a new builder would break:

* **v2 is the pre-INT-002 behaviour, byte for byte.** Before INT-002 there was
  no versioning at all — exactly one shape — so ``v2`` *is* that shape and the
  field default is ``"v2"``. The pre-change wire bodies are embedded below as
  literals, and ``tests/integration/test_abha_services.py`` pins the same claim
  at the endpoint and at the transport. Both were checked against the
  implementation at ``f1c0556`` — the literals are captures, not a reading of
  the current code.
* **Neither version can echo the link token** (ABD-012). Both builders select
  their output keys explicitly, so a credential cannot reach the wire by being
  passed in, and the tests inject ``link_token`` to prove it.

**v3 is provisional.** The official ABDM sandbox spec is unresolved — see the
REG-009 entry under Known gaps in ``docs/traceability.md`` — so v3's shape here
is a *documented placeholder* derived only from the vocabulary this repository
already exchanges with the gateway (camelCase keys such as ``requestId``,
``sourceApp``, ``abhaNumber``). It is not a claim about the real ABDM API and
must be re-verified when the spec is confirmed.
"""
import json

import httpx
import pytest

from apps.abdm_gateway.client import (
    ABDMUnsupportedVersionError,
    DEFAULT_API_VERSION,
    SUPPORTED_API_VERSIONS,
    build_callback_ack,
    build_profile_share_request,
    declared_api_version,
    require_supported_api_version,
)

pytestmark = [pytest.mark.unit]

#: A profile-share payload in the shape the callback contract already uses.
REQUEST_PAYLOAD = {
    "requestId": "req-1",
    "facilityId": "hip-123",
    "profile": {"abhaNumber": "123456789012"},
}

#: The body ``ABDMClient.create_abha`` put on the wire before INT-002, captured
#: from the pre-change implementation with ``httpx``'s compact JSON encoding.
#: v2 must keep producing exactly these bytes. The literal is not a guess:
#: :func:`_wire_bytes` below builds the request ``httpx`` would have sent for the
#: same payload, so the pin is checked against the real encoder.
PRE_CHANGE_CREATE_ABHA_BODY = (
    '{"aadhaar":"XXXXXXXXXXXX","mobile":"9876543210","otp":"123456"}'
)
PRE_CHANGE_CREATE_ABHA_INPUT = {
    "aadhaar": "XXXXXXXXXXXX", "mobile": "9876543210", "otp": "123456",
}


def _wire_bytes(payload):
    """The bytes ``httpx`` puts on the wire for ``json=payload`` — no network.

    ``json.dumps(..., separators=(",", ":"))`` is a stand-in for that encoding,
    and a stand-in is exactly the kind of approximation this pin exists to
    avoid: if the two ever disagree, a "byte-for-byte" claim would be about the
    stand-in rather than about the wire.
    """
    request = httpx.Request("POST", "https://healthidsbx.abdm.gov.in/api/v1", json=payload)
    return request.content


#: The acknowledgement fields the view builds before handing them to a builder,
#: in the exact key order ``ABHACallbackAckSerializer`` emits today.
ACK_FIELDS = {
    "status": "ok",
    "token": "5618da68-8d7c-4d17-b44e-d7edb28730e0",
    "request_id": "req-1",
    "patient_id": "cffb2ff9-5bc8-4958-80d6-a32478c36ad7",
    "consent_event": {
        "timestamp": "2026-10-16T02:31:57.292506-05:00",
        "source_app": "ABDM",
        "purpose": "registration",
        "facility_id": "41435262-8821-4d6a-9e92-6b3afb0244ae",
    },
}

#: The duplicate (replayed) acknowledgement, whose literal shape differs from the
#: serializer's: it carries a ``detail`` and no consent event.
DUPLICATE_ACK_FIELDS = {
    "status": "duplicate",
    "detail": "This request was already processed",
    "request_id": "req-1",
    "token": "5618da68-8d7c-4d17-b44e-d7edb28730e0",
    "patient_id": "cffb2ff9-5bc8-4958-80d6-a32478c36ad7",
}


class TestVersionRegistry:
    """The supported set is declared once, and it is what validation enforces."""

    def test_the_supported_set_is_v2_and_v3(self):
        """INT-002: an older and a newer version, both served.

        Asserted rather than derived so that dropping a version from the
        registry — which would silently change what the callback answers and
        what ``for_adapter`` dispatches — fails here instead.
        """
        assert SUPPORTED_API_VERSIONS == ("v2", "v3")

    def test_the_default_is_v2_the_pre_versioning_shape(self):
        """The default must be the behaviour that already existed (INT-002).

        ``v2`` reproduces the single unversioned shape exactly, so a tenant with
        no adapter row and a gateway that declares nothing keeps today's
        contract byte for byte.
        """
        assert DEFAULT_API_VERSION == "v2"
        assert DEFAULT_API_VERSION in SUPPORTED_API_VERSIONS

    @pytest.mark.parametrize("api_version", SUPPORTED_API_VERSIONS)
    def test_every_supported_version_is_accepted(self, api_version):
        assert require_supported_api_version(api_version) == api_version

    @pytest.mark.parametrize(
        "value",
        ["v1", "v1.0", "v4", "V2", "2", "", None, 3, ["v2"]],
    )
    def test_anything_outside_the_set_is_refused(self, value):
        """Fail closed, with an error that names the supported set.

        Near-misses matter as much as nonsense: ``"v1.0"`` is the label the
        ABDM developer forum uses (architecture doc section 8.2) and
        ``tests/integration/test_abdm_sandbox.py`` still calls its replays
        "v1.0", so a deployment that guesses at the vocabulary must be told no
        rather than silently served a shape nobody pinned.
        """
        with pytest.raises(ABDMUnsupportedVersionError) as excinfo:
            require_supported_api_version(value)

        message = str(excinfo.value)
        for supported in SUPPORTED_API_VERSIONS:
            assert supported in message

    def test_whitespace_is_tolerated_but_case_is_not(self):
        """A padded declaration is the same version; a differently-cased one is not.

        Surrounding whitespace is a transport artefact and is stripped. Case is
        not: folding ``"V3"`` into ``"v3"`` would decide the acknowledgement's
        shape by guessing at what the sender meant, and the whole point of the
        registry is that the shape is never guessed.
        """
        assert require_supported_api_version("  v3  ") == "v3"
        with pytest.raises(ABDMUnsupportedVersionError):
            require_supported_api_version("V3")


class TestDeclaredApiVersion:
    """The version a callback declares, read from the payload key."""

    def test_the_declaration_is_read_from_the_payload(self):
        assert declared_api_version({"apiVersion": "v3"}) == "v3"

    def test_absent_declaration_is_none_not_an_error(self):
        """No declaration is a legitimate state, and falls back down the chain."""
        assert declared_api_version({"requestId": "req-1"}) is None

    @pytest.mark.parametrize("payload", [{"apiVersion": ""}, {"apiVersion": None}])
    def test_an_empty_declaration_is_treated_as_absent(self, payload):
        """An empty value is a sender that declared nothing, not a bad version.

        Answering 422 here would refuse a callback whose intent is unambiguous
        (speak the default) over a field the sender left blank.
        """
        assert declared_api_version(payload) is None

    def test_a_non_string_declaration_is_ignored_rather_than_coerced(self):
        """Coercing ``{"apiVersion": {"v": 3}}`` into a version would be a guess."""
        assert declared_api_version({"apiVersion": {"v": 3}}) is None

    def test_a_non_dict_payload_declares_nothing(self):
        assert declared_api_version(["not", "a", "dict"]) is None


class TestProfileShareRequestBuilders:
    """The outbound body, per version."""

    def test_v2_reproduces_the_pre_change_body_byte_for_byte(self):
        """v2 is what the client would have sent with no version support at all.

        The literal is the pre-change ``create_abha`` wire body. If v2 reshaped
        the payload in any way, every existing ABDM counter deployment would
        change on the wire.
        """
        built = build_profile_share_request("v2", PRE_CHANGE_CREATE_ABHA_INPUT)

        assert _wire_bytes(built) == PRE_CHANGE_CREATE_ABHA_BODY.encode("ascii")
        # The encoder itself, so the literal above stays an observed fact rather
        # than an assertion about how httpx is believed to serialise JSON.
        assert _wire_bytes(PRE_CHANGE_CREATE_ABHA_INPUT) == (
            PRE_CHANGE_CREATE_ABHA_BODY.encode("ascii")
        )

    def test_v3_changes_the_wire_bytes(self):
        """The other half of the equivalence claim: v3 is observably not v2.

        Without this, "v2 is the pre-change bytes" could be true because v3 did
        nothing at all, and INT-002's "newer version" would be a claim with no
        body behind it.
        """
        built = build_profile_share_request("v3", PRE_CHANGE_CREATE_ABHA_INPUT)

        assert _wire_bytes(built) != PRE_CHANGE_CREATE_ABHA_BODY.encode("ascii")

    def test_v2_returns_the_payload_unchanged(self):
        assert build_profile_share_request("v2", REQUEST_PAYLOAD) == REQUEST_PAYLOAD

    def test_v2_does_not_alias_the_caller_payload(self):
        """A copy, not the same dict: a builder must not hand back a live handle."""
        payload = dict(REQUEST_PAYLOAD)
        built = build_profile_share_request("v2", payload)

        built["requestId"] = "mutated"
        assert payload["requestId"] == "req-1"

    def test_v3_declares_the_version_it_is_speaking(self):
        """v3's body carries the version, and nothing else changes.

        Deliberately minimal: with the sandbox spec unresolved (REG-009) the only
        newer-flow difference this repository can justify is the declaration
        itself. Inventing a nested envelope or renamed fields here would be a
        claim about ABDM's API that nothing verifies.
        """
        built = build_profile_share_request("v3", REQUEST_PAYLOAD)

        assert built["apiVersion"] == "v3"
        for key, value in REQUEST_PAYLOAD.items():
            assert built[key] == value

    def test_v3_does_not_mutate_the_caller_payload(self):
        payload = dict(REQUEST_PAYLOAD)
        build_profile_share_request("v3", payload)

        assert "apiVersion" not in payload

    def test_the_two_versions_are_observably_different(self):
        """Without this, "supports both versions" could be a claim with no body."""
        assert build_profile_share_request("v2", REQUEST_PAYLOAD) != (
            build_profile_share_request("v3", REQUEST_PAYLOAD)
        )

    def test_an_unsupported_version_is_refused_before_anything_is_built(self):
        with pytest.raises(ABDMUnsupportedVersionError):
            build_profile_share_request("v9", REQUEST_PAYLOAD)


class TestCallbackAckBuilders:
    """The acknowledgement, per version."""

    def test_v2_is_the_pre_change_acknowledgement(self):
        assert build_callback_ack("v2", ACK_FIELDS) == ACK_FIELDS

    def test_v2_preserves_the_pre_change_key_order(self):
        """Key order is bytes on the wire, so v2 cannot reorder the fields."""
        assert list(build_callback_ack("v2", ACK_FIELDS)) == list(ACK_FIELDS)
        assert list(build_callback_ack("v2", DUPLICATE_ACK_FIELDS)) == list(
            DUPLICATE_ACK_FIELDS
        )

    def test_v2_reproduces_the_pre_change_duplicate_acknowledgement(self):
        """The replay path builds its fields as a literal, not through the
        serializer, and its shape (a ``detail``, no consent event) is part of the
        pre-change contract too."""
        assert build_callback_ack("v2", DUPLICATE_ACK_FIELDS) == DUPLICATE_ACK_FIELDS

    def test_v3_answers_in_the_gateway_s_camel_case_vocabulary(self):
        body = build_callback_ack("v3", ACK_FIELDS)

        assert body == {
            "apiVersion": "v3",
            "status": "ok",
            "token": "5618da68-8d7c-4d17-b44e-d7edb28730e0",
            "requestId": "req-1",
            "patientId": "cffb2ff9-5bc8-4958-80d6-a32478c36ad7",
            "consentEvent": {
                "timestamp": "2026-10-16T02:31:57.292506-05:00",
                "sourceApp": "ABDM",
                "purpose": "registration",
                "facilityId": "41435262-8821-4d6a-9e92-6b3afb0244ae",
            },
        }

    def test_v3_answers_the_replay_path_in_the_same_vocabulary(self):
        """The duplicate branch's fields must survive the rename too.

        ``detail`` is ours rather than the gateway's, so it keeps its name; the
        two identifiers it carries are renamed like any other.
        """
        body = build_callback_ack("v3", DUPLICATE_ACK_FIELDS)

        assert body["status"] == "duplicate"
        assert body["detail"] == "This request was already processed"
        assert body["requestId"] == "req-1"
        assert body["patientId"] == DUPLICATE_ACK_FIELDS["patient_id"]
        assert "consentEvent" not in body

    def test_v3_keeps_a_null_token_null(self):
        """The ambiguous branch acknowledges with a null token (ABD-009)."""
        fields = dict(ACK_FIELDS, status="ambiguous", token=None)

        assert build_callback_ack("v3", fields)["token"] is None

    def test_v3_keeps_a_null_consent_event_null(self):
        assert build_callback_ack("v3", dict(ACK_FIELDS, consent_event=None)) == {
            "apiVersion": "v3",
            "status": "ok",
            "token": ACK_FIELDS["token"],
            "requestId": "req-1",
            "patientId": ACK_FIELDS["patient_id"],
            "consentEvent": None,
        }

    def test_the_two_versions_are_observably_different(self):
        """Without this, "supports both versions" could be a claim with no body."""
        assert build_callback_ack("v2", ACK_FIELDS) != build_callback_ack("v3", ACK_FIELDS)

    def test_an_unsupported_version_is_refused_before_anything_is_built(self):
        with pytest.raises(ABDMUnsupportedVersionError):
            build_callback_ack("v9", ACK_FIELDS)


class TestLinkTokenIsNeverAcknowledged:
    """ABD-012, pinned per version: the credential cannot reach either wire.

    ``store_link_token`` seals the link token into ``link_token_enc`` and the
    gateway is never told its value. A versioned ack is where that invariant is
    most likely to be broken — a new builder that copies the fields it is handed
    would carry it — so the token is *injected* into the fields here and must
    come out absent in both versions.
    """

    @pytest.mark.parametrize("api_version", SUPPORTED_API_VERSIONS)
    def test_an_injected_link_token_is_dropped(self, api_version):
        fields = dict(ACK_FIELDS, link_token="c2VjcmV0LWxpbmstdG9rZW4")

        assert "link_token" not in build_callback_ack(api_version, fields)

    @pytest.mark.parametrize("api_version", SUPPORTED_API_VERSIONS)
    def test_an_injected_link_token_is_dropped_on_the_replay_path_too(self, api_version):
        fields = dict(DUPLICATE_ACK_FIELDS, link_token="c2VjcmV0LWxpbmstdG9rZW4")

        body = build_callback_ack(api_version, fields)

        assert "link_token" not in body
        assert "c2VjcmV0LWxpbmstdG9rZW4" not in json.dumps(body)

    @pytest.mark.parametrize("api_version", SUPPORTED_API_VERSIONS)
    def test_an_unexpected_key_is_never_passed_through(self, api_version):
        """Neither builder forwards a key it does not name itself.

        A pass-through would make "what does the gateway see" a function of
        whatever the view happened to build, which is the opposite of a pinned
        contract.
        """
        assert "future_field" not in build_callback_ack(
            api_version, dict(ACK_FIELDS, future_field="value")
        )