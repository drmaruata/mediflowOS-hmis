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

**The resolution contract, which is the opposite of "fail closed" on labels.**
A version *label* is never refused. The official ABDM spec is unresolved (REG-009),
so no string a gateway can send can be proven unsupported, and refusing one puts a
tenant's whole scan-and-share channel down over a wording difference. So
:func:`resolve_api_version` resolves an exact label to itself, a documented alias
(``"v1.0"`` — the label this repository's own architecture doc and sandbox
replay use) to its target, and *anything else* to ``DEFAULT_API_VERSION`` with a
warning naming the label and the tenant. Only a **malformed** declaration — a
list, an object or a number where a version label belongs — is refused, because
that is a broken payload rather than a different vocabulary. INT-002 asks for two
versions to be *served*; it does not ask for unknown ones to be rejected.

**v3 is provisional.** The official ABDM sandbox spec is unresolved — see the
REG-009 entry under Known gaps in ``docs/traceability.md`` — so v3's shape here
is a *documented placeholder* derived only from the vocabulary this repository
already exchanges with the gateway (camelCase keys such as ``requestId``,
``sourceApp``, ``abhaNumber``). It is not a claim about the real ABDM API and
must be re-verified when the spec is confirmed.
"""
import json
import logging

import httpx
import pytest

from apps.abdm_gateway.client import (
    ABDMUnsupportedVersionError,
    API_VERSION_ALIASES,
    API_VERSION_PAYLOAD_KEY,
    DEFAULT_API_VERSION,
    SUPPORTED_API_VERSIONS,
    build_callback_ack,
    build_profile_share_request,
    declared_api_version,
    resolve_api_version,
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
    """The supported set, the aliases onto it, and what an unknown label gets.

    One rule, pinned four ways: an **exact** label resolves to itself, a
    **documented alias** resolves to its target, an **unknown string** resolves
    to the default shape with a warning, and a **non-string** is refused. Each
    assertion below names a case the other three do not cover, so none of them
    can be satisfied by a rule that only handles part of the contract.
    """

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
    def test_an_exact_label_resolves_to_itself(self, api_version):
        assert resolve_api_version(api_version) == api_version

    def test_the_gateway_documented_older_label_is_an_alias_of_the_default(self):
        """``v1.0`` is this repository's own word for the legacy flow.

        Architecture doc section 8.2 records v1.0 and v3 paths coexisting on the
        gateway, and ``tests/integration/test_abdm_sandbox.py`` still calls its
        replays "v1.0". So the legacy label is an **accepted alias** of the v2
        shape, served deliberately rather than by accident: without this entry
        those calls would merely fall back, and a future reader would not know
        the vocabulary mismatch is a decision instead of a shrug.
        """
        assert API_VERSION_ALIASES["v1.0"] == "v2"
        assert API_VERSION_ALIASES["1.0"] == "v2"

    @pytest.mark.parametrize(
        "label,target",
        sorted(API_VERSION_ALIASES.items()),
        ids=sorted(API_VERSION_ALIASES),
    )
    def test_an_alias_is_served_in_the_aliased_shape(self, label, target, caplog):
        """Non-vacuous in three directions.

        ``target in SUPPORTED_API_VERSIONS`` keeps the table from pointing at a
        version this deployment cannot build; ``label not in
        SUPPORTED_API_VERSIONS`` keeps it from being a redundant second spelling
        of an entry that already exists. And **no fallback warning** is what
        separates an alias from an unrecognised label — both produce ``v2``
        today, so without it this whole test would pass against an *empty* alias
        table, which is exactly the state that erased the deliberate mapping.
        """
        with caplog.at_level(logging.WARNING, logger="apps.abdm_gateway.client"):
            resolved = resolve_api_version(label)

        assert resolved == target
        assert target in SUPPORTED_API_VERSIONS
        assert label not in SUPPORTED_API_VERSIONS
        assert caplog.records == [], caplog.text

    @pytest.mark.parametrize(
        "label", ["v1", "v4", "V3", "2", "v2.0", "v3.1", "3.0", "latest"]
    )
    def test_an_unrecognised_label_is_served_in_the_default_shape(self, label):
        """The ruling: an unknown string is never refused, only warned about.

        Before this contract the same call raised, so every one of these labels
        took a signed, authentic, in-window callback from a full 200 flow to a
        permanent 422 — no patient, no token, no consent row.
        """
        assert resolve_api_version(label) == DEFAULT_API_VERSION

    @pytest.mark.parametrize(
        "label", ["v1", "v4", "V3", "2", "v2.0", "v3.1", "3.0", "latest"]
    )
    def test_an_unrecognised_label_is_logged_with_the_tenant_and_the_label(
        self, label, caplog
    ):
        """The fallback is silent only if the operator never learns of it.

        Both facts the operator needs are in the line: which label the gateway
        sent, and whose channel is being answered in the wrong shape. No patient
        data is involved — a version label is a contract token from an
        already-authenticated body.
        """
        with caplog.at_level(logging.WARNING, logger="apps.abdm_gateway.client"):
            resolve_api_version(label, tenant_id="11111111-2222-3333-4444-555555555555")

        assert "11111111-2222-3333-4444-555555555555" in caplog.text
        assert repr(label) in caplog.text
        assert DEFAULT_API_VERSION in caplog.text

    @pytest.mark.parametrize(
        "value", [["v2"], {"version": "v3"}, 3, 2.0, True]
    )
    def test_a_malformed_declaration_is_refused(self, value):
        """A list, an object or a number where a label belongs is a broken payload.

        This is the *only* refusal the registry makes, and it is the one the
        endpoint turns into a 422: nothing here can be read as a version, so
        there is nothing to serve and no honest fallback to guess. It is also
        the asymmetry that a non-string used to get the other way round: it was
        silently served as ``v2``, which hides a broken sender behind a
        successful-looking acknowledgement.
        """
        with pytest.raises(ABDMUnsupportedVersionError) as excinfo:
            resolve_api_version(value)

        assert excinfo.value.requested == value
        for supported in SUPPORTED_API_VERSIONS:
            assert supported in str(excinfo.value)

    def test_nothing_declared_resolves_to_the_default_shape(self):
        """An absent declaration is the pre-versioning contract, not a failure."""
        assert resolve_api_version(None) == DEFAULT_API_VERSION

    def test_surrounding_whitespace_is_stripped(self):
        """A padded declaration is the same label; a transport artefact, not a version."""
        assert resolve_api_version("  v3  ") == "v3"

    def test_a_differently_cased_label_is_not_that_version(self, caplog):
        """Case is still not folded — but the call is still served.

        ``"V3"`` must not silently become ``"v3"``: that would decide the
        acknowledgement's shape by guessing at what the sender meant. It is
        served in the *default* shape instead, and the warning says so.
        """
        with caplog.at_level(logging.WARNING, logger="apps.abdm_gateway.client"):
            resolved = resolve_api_version("V3")

        assert resolved == DEFAULT_API_VERSION
        assert "'V3'" in caplog.text


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

    @pytest.mark.parametrize(
        "declared,expected",
        [({"version": "v3"}, {"version": "v3"}), ({"v": 3}, {"v": 3}), (3, 3), ([1, 2], [1, 2])],
    )
    def test_a_non_string_declaration_is_surfaced_rather_than_coerced(self, declared, expected):
        """Neither guessed at nor dropped: handed on unchanged so it can be refused.

        This is the other half of the refusal contract. Returning ``None`` here
        — which is what this function used to do — made a broken sender
        indistinguishable from one that said nothing, and it was then answered
        ``200`` in the default shape as though it had been understood. Surfacing
        it is what lets the endpoint answer 422 for a malformed declaration.
        """
        assert declared_api_version({"apiVersion": declared}) == expected

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

    def test_the_bound_version_wins_over_one_handed_in_on_the_payload(self):
        """A v3 client cannot put ``"v2"`` on the wire while reporting v3.

        The stamp is the client's, not the caller's: the payload used to be
        merged *over* the version, so a caller-supplied ``apiVersion`` silently
        decided the shape on the wire while ``client.api_version`` said
        otherwise — two truths, and the wire carried the wrong one.
        """
        built = build_profile_share_request(
            "v3", dict(PRE_CHANGE_CREATE_ABHA_INPUT, apiVersion="v2")
        )

        assert built[API_VERSION_PAYLOAD_KEY] == "v3"
        assert list(built)[0] == API_VERSION_PAYLOAD_KEY

    def test_v2_does_not_strip_a_version_the_caller_handed_in(self):
        """The pre-versioning body is the caller's payload, verbatim.

        ``v2`` is the pre-INT-002 bytes, so it must neither gain nor lose a key
        the old client would not have sent — the version stamp belongs to v3
        alone.
        """
        built = build_profile_share_request(
            "v2", dict(PRE_CHANGE_CREATE_ABHA_INPUT, apiVersion="v3")
        )

        assert built == dict(PRE_CHANGE_CREATE_ABHA_INPUT, apiVersion="v3")

    def test_v3_does_not_mutate_the_caller_payload(self):
        payload = dict(REQUEST_PAYLOAD)
        build_profile_share_request("v3", payload)

        assert "apiVersion" not in payload

    def test_the_two_versions_are_observably_different(self):
        """Without this, "supports both versions" could be a claim with no body."""
        assert build_profile_share_request("v2", REQUEST_PAYLOAD) != (
            build_profile_share_request("v3", REQUEST_PAYLOAD)
        )

    def test_an_unrecognised_label_builds_the_pre_versioning_body(self):
        """A builder never refuses a string: an unknown label builds v2's body."""
        assert build_profile_share_request(
            "v9", PRE_CHANGE_CREATE_ABHA_INPUT
        ) == build_profile_share_request("v2", PRE_CHANGE_CREATE_ABHA_INPUT)

    def test_a_malformed_version_argument_is_refused_before_anything_is_built(self):
        with pytest.raises(ABDMUnsupportedVersionError):
            build_profile_share_request(["v3"], REQUEST_PAYLOAD)

    def test_a_padded_or_aliased_label_builds_the_shape_it_names(self):
        """The *resolved* label dispatches, not the raw argument.

        The registry strips whitespace and maps aliases, but both builders used
        to dispatch on the string they were handed, so ``"  v3  "`` validated as
        v3 and then quietly built the v2 body.
        """
        assert build_profile_share_request("  v3  ", REQUEST_PAYLOAD) == (
            build_profile_share_request("v3", REQUEST_PAYLOAD)
        )
        assert build_profile_share_request("v1.0", REQUEST_PAYLOAD) == (
            build_profile_share_request("v2", REQUEST_PAYLOAD)
        )


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

    def test_an_unrecognised_label_builds_the_pre_change_acknowledgement(self):
        """A builder never refuses a string: an unknown label builds v2's ack."""
        body = build_callback_ack("v9", ACK_FIELDS)

        assert body == ACK_FIELDS
        assert list(body) == list(ACK_FIELDS)

    def test_a_malformed_version_argument_is_refused_before_anything_is_built(self):
        with pytest.raises(ABDMUnsupportedVersionError):
            build_callback_ack({"version": "v3"}, ACK_FIELDS)

    def test_a_padded_or_aliased_label_builds_the_shape_it_names(self):
        """The *resolved* label dispatches, not the raw argument.

        Both builders used to validate through the registry and then dispatch on
        the string they were handed, so ``"  v3  "`` passed validation and built
        the v2 body. Aliases hit the same gap.
        """
        assert build_callback_ack("  v3  ", ACK_FIELDS) == build_callback_ack(
            "v3", ACK_FIELDS
        )
        assert build_callback_ack("v1.0", ACK_FIELDS) == build_callback_ack(
            "v2", ACK_FIELDS
        )

    @pytest.mark.parametrize("label", ["v1.0", "1.0"])
    def test_a_builder_given_an_alias_emits_no_fallback_warning(self, label, caplog):
        """An alias is a deliberate mapping, so it must not look like a shrug.

        Without this the alias and the unknown-label branches are
        indistinguishable by output *and* by log, and the alias table could be
        deleted without a single test noticing.
        """
        with caplog.at_level(logging.WARNING, logger="apps.abdm_gateway.client"):
            body = build_callback_ack(label, ACK_FIELDS)

        assert body == ACK_FIELDS
        assert caplog.records == [], caplog.text


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
