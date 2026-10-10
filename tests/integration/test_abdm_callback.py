"""Tests for the ABDM profile-share callback endpoint.

History: this file originally asserted the endpoint answered 501 and wrote
nothing, which was the honest state while the seven architecture doc section 8.4
requirements were outstanding. The callback is now implemented, so these tests
pin the behaviour that replaced it.

The route stays ``AllowAny`` because the gateway carries no user JWT.
Authentication therefore happens *inside* the view, not by DRF, and that is the
single most important thing to keep pinned here: an anonymous route that reaches
a database write without authenticating first would let anyone register
patients into a real hospital.

ABD-005 is enforced with a real HMAC: every successful call posts a signature
computed over the exact bytes the client sends (``_signed_request`` serializes
the payload once and signs those bytes), and the view re-computes the digest
over the raw body it receives. Tests that must change the bytes after signing
post the mutated body with the original signature — the view computes over
what it receives, so the digest no longer matches.

The last two of the seven architecture doc section 8.4 requirements close here:
ABD-011 (the consent event is written to ``abdm.consent_event``, not merely built
in memory) and ABD-012 (the link token is sealed at rest and never echoed back).
Both are pinned below, including the data-minimisation rule that the consent
table carries no profile data at all.

The ABD-008/ABD-009 branch matrix is pinned here too: an exact ABHA match links,
a single demographic candidate links as weak evidence, several candidates create
no link at all but one verification-queue entry, and no match registers a
provisional patient. Each branch asserts the patient row count it leaves behind,
because the multi-candidate branch used to collapse into the provisional create
— a scan for a real, registered patient silently minting a second record.
"""
import hashlib
import hmac
import json
import uuid

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.abdm_gateway.models import ABHACallbackLog, ConsentEvent
from apps.identity_tenancy.models import (
    Department, Facility, Role, Tenant, UserMembership,
)
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.opd.models import Token
from apps.patient_registry.models import Patient
from common.crypto import decrypt, derive_keys

CALLBACK_URL = "/api/v1/abdm-callbacks/"


def _signed_request(payload, secret=None):
    """Serialize once and sign the exact bytes the client will post.

    The view re-computes the HMAC over the raw request body, so the digest has
    to cover the same bytes that go on the wire: serializing twice could reorder
    keys and break the signature even for a legitimate call. Returns the body
    bytes and the ``HTTP_X_ABDM_SIGNATURE`` header dict.
    """
    secret = settings.ABDM_CLIENT_SECRET if secret is None else secret
    body_bytes = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return body_bytes, {"HTTP_X_ABDM_SIGNATURE": signature}


def _post(client, payload, count=1, **kwargs):
    """Post ``payload`` signed, returning the last response.

    ``count`` repeats the same signed request (a replay) and returns the final
    response — replaying must send identical bytes, which requires one signed
    body reused verbatim.
    """
    body, headers = _signed_request(payload, **kwargs)
    response = None
    for _ in range(count):
        response = client.post(
            CALLBACK_URL, body, content_type="application/json", **headers
        )
    return response


def _tenant_with_opd(slug="abdm-hospital", hip_id="hip-123"):
    tenant = Tenant.objects.create(name="ABDM Hospital", slug=slug)
    facility = Facility.objects.create(
        tenant=tenant, name="Main Campus", abdm_hip_id=hip_id,
    )
    department = Department.objects.create(
        tenant=tenant, facility=facility, name="Medicine",
        effective_from="2026-01-01", opd_enabled=True,
    )
    return tenant, facility, department


def _payload(**overrides):
    body = {
        "requestId": "req-1",
        "facilityId": "hip-123",
        "timestamp": timezone.now().isoformat(),
        "profile": {"abhaNumber": "123456789012"},
    }
    body.update(overrides)
    return body


@pytest.mark.integration
@pytest.mark.django_db
def test_abdm_callback_rejects_unauthenticated_call():
    """An anonymous write attempt must be refused before any work happens.

    DRF does not do this: the route is AllowAny. If this ever returns 200, the
    gateway is unauthenticated and anyone can write into a tenant. The tenant is
    set up so the call would otherwise succeed — the rejection has to come from
    authentication, not from the payload failing later.
    """
    _tenant_with_opd()
    response = APIClient().post(CALLBACK_URL, _payload(), format="json")

    assert response.status_code == 401
    assert response.json()["status"] == "rejected"


@pytest.mark.integration
@pytest.mark.django_db
def test_unauthenticated_call_writes_nothing():
    """A refused call must not leave rows behind."""
    _tenant_with_opd()
    APIClient().post(CALLBACK_URL, _payload(), format="json")

    assert ABHACallbackLog.objects.count() == 0
    assert Token.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_legacy_presence_only_headers_are_rejected():
    """The pre-ABD-005 presence fallbacks no longer authenticate (ABD-005).

    The previous implementation accepted any non-empty X-Authorization header
    or Bearer token. A header without a valid HMAC must now be refused, or an
    attacker with either legacy header shape could write into a tenant.
    """
    _tenant_with_opd()
    body, _ = _signed_request(_payload())
    response = APIClient().post(
        CALLBACK_URL,
        body,
        content_type="application/json",
        HTTP_X_AUTHORIZATION="gateway-shared-secret",
    )

    assert response.status_code == 401
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_abdm_callback_processes_an_authenticated_call():
    """A valid HMAC-signed, well-formed call issues a token and logs it."""
    tenant, _, department = _tenant_with_opd()
    response = _post(APIClient(), _payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["request_id"] == "req-1"

    log = ABHACallbackLog.objects.get(request_id="req-1")
    assert str(log.tenant_id) == str(tenant.id)
    assert log.token_issued == body["token"]
    assert Token.objects.get(id=body["token"]).department_id == department.id


@pytest.mark.integration
@pytest.mark.django_db
def test_unmatched_profile_is_registered_pending_verification():
    """A scan for an unknown patient creates a record, not a verified identity.

    Nobody has checked the demographics against an ID document, so the patient
    must land in the verification queue (REG-004).
    """
    _tenant_with_opd()
    response = _post(APIClient(), _payload())

    patient = Patient.objects.get(id=response.json()["patient_id"])
    assert patient.verification_status == "pending"
    assert patient.abha_number == "123456789012"
    assert patient.consent_flags["abdm_scan_and_share"] is True


# --- ABD-008/ABD-009: the match branch matrix --------------------------------
#
# Four branches, each asserting the patient row count it leaves behind, because
# the multi-candidate branch used to collapse into the provisional create: a scan
# for a real, already-registered patient silently minted a second record and a
# token against it.


def _demographic_profile(name="Asha Verma", year=1984, gender="F"):
    """A profile that carries demographics only — no ABHA number (ABD-008).

    Without an ABHA number the match can only be demographic, which is what
    exercises the candidates/none branches.
    """
    return {"demographics": {"name": name, "yearOfBirth": year, "gender": gender}}


def _make_queue_client(tenant, username):
    """JWT-authenticated client whose token carries the tenant's claims.

    Same shape as the registration suite's helper: the tenant claim on the
    access token is what ``TenantBoundJWTAuthentication`` binds, so this client
    reads the verification queue the way front-desk staff do.
    """
    user = get_user_model().objects.create_user(
        username=username, password="testpass123"
    )
    role = Role.objects.create(tenant=tenant, name=f"role-{username}", permissions=[])
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    refresh = TenantAwareTokenSerializer.get_token(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


@pytest.mark.integration
@pytest.mark.django_db
def test_exact_abha_match_links_without_demoting_a_verified_patient():
    """An exact ABHA match links the existing record and leaves its status alone.

    ABHA is a strong identifier: the gateway is restating a number the front
    desk already confirmed, so linking must not write ``pending`` over
    ``verified`` and put a confirmed patient back in the verification queue.
    The target is deliberately created ``verified`` with different demographics
    to prove the ABHA digest path — not a name match — found it.
    """
    tenant, _, _ = _tenant_with_opd()
    target = Patient.objects.create(
        tenant_id=tenant.id, uhid="UHID-ABHA-EXACT", abha_number="123456789012",
        verification_status="verified",
        demographics={"name": "Someone Else Entirely", "gender": "F", "yearOfBirth": 1970},
    )

    response = _post(APIClient(), _payload())

    assert response.status_code == 200
    body = response.json()
    assert body["token"] is not None
    assert body["patient_id"] == str(target.id)
    target.refresh_from_db()
    assert target.verification_status == "verified"
    # Linked, not registered: no second patient row exists.
    assert Patient.objects.count() == 1
    assert Token.objects.count() == 1


@pytest.mark.integration
@pytest.mark.django_db
def test_single_demographic_candidate_links_and_stays_pending():
    """One demographic match links, but as weak evidence: the record stays pending.

    The profile carries no ABHA number, so name + birth year + gender is all the
    evidence there is. The link is kept (a token against the right patient is
    better than a duplicate), yet nobody has confirmed the identity, so the
    record must stay in the verification queue for the front desk.
    """
    tenant, _, _ = _tenant_with_opd()
    candidate = Patient.objects.create(
        tenant_id=tenant.id, uhid="UHID-DEMO-ONE",
        demographics={"name": "Asha Verma", "gender": "F", "year_of_birth": 1984},
    )

    response = _post(APIClient(), _payload(profile=_demographic_profile()))

    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == str(candidate.id)
    assert body["token"] is not None
    candidate.refresh_from_db()
    assert candidate.verification_status == "pending"
    assert Patient.objects.count() == 1
    assert Token.objects.count() == 1


@pytest.mark.integration
@pytest.mark.django_db
def test_demographic_match_never_demotes_a_verified_patient():
    """A gateway guess must not demote a front-desk-verified record (ABD-009).

    The single candidate is already ``verified`` — somebody checked the identity
    document. A demographic-only match is weak evidence, so it may confirm
    nothing new, but writing ``pending`` over ``verified`` would queue a
    confirmed patient for re-verification, a demotion the gateway has no
    standing to make.
    """
    tenant, _, _ = _tenant_with_opd()
    candidate = Patient.objects.create(
        tenant_id=tenant.id, uhid="UHID-DEMO-VERIFIED", verification_status="verified",
        demographics={"name": "Asha Verma", "gender": "F", "year_of_birth": 1984},
    )

    response = _post(APIClient(), _payload(profile=_demographic_profile()))

    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == str(candidate.id)
    candidate.refresh_from_db()
    assert candidate.verification_status == "verified"


@pytest.mark.integration
@pytest.mark.django_db
def test_multiple_candidates_queue_for_verification_without_a_token():
    """ABD-009: two demographic matches create no link and issue no token.

    Linking either candidate would be a coin toss between two registered
    patients, so the callback creates exactly one verification-queue entry
    (``ambiguous``), records both candidate ids on the log for the clerk who
    resolves it, and acknowledges 200 with a null token: the scan was received
    and the consent honoured, but identity resolution is queued work.
    """
    tenant, _, _ = _tenant_with_opd()
    first = Patient.objects.create(
        tenant_id=tenant.id, uhid="UHID-AMB-1",
        demographics={"name": "Shared Name", "gender": "M", "year_of_birth": 1980},
    )
    second = Patient.objects.create(
        tenant_id=tenant.id, uhid="UHID-AMB-2",
        demographics={"name": "Shared Name", "gender": "M", "year_of_birth": 1980},
    )

    response = _post(
        APIClient(),
        _payload(profile=_demographic_profile(name="Shared Name", year=1980, gender="M")),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token"] is None

    queue = Patient.objects.get(verification_status="ambiguous")
    assert body["patient_id"] == str(queue.id)
    assert queue.uhid.startswith("ABDM")
    assert queue.demographics["name"] == "Shared Name"
    assert queue.demographics["yearOfBirth"] == 1980
    assert queue.consent_flags["abdm_scan_and_share"] is True
    # The profile carries no ABHA number, so the queue entry has none either.
    assert queue.abha_number is None
    # Two candidates plus exactly one queue entry — no provisional patient.
    assert Patient.objects.count() == 3

    log = ABHACallbackLog.objects.get(request_id="req-1")
    assert log.status == "ambiguous"
    assert log.token_issued is None
    assert log.matched_patient_id == queue.id
    # Data minimisation: candidate ids and a reason, never a name or identifier.
    assert {(row["patient_id"], row["reason"]) for row in log.match_candidates} == {
        (str(first.id), "demographic"),
        (str(second.id), "demographic"),
    }
    assert "Shared Name" not in json.dumps(log.match_candidates)
    # Nothing to link yet: no link token is minted for an unresolved identity.
    assert log.link_token_enc is None
    assert Token.objects.count() == 0
    # The consent happened at scan time (DPDP); only identity is queued.
    assert ConsentEvent.objects.count() == 1
    assert ConsentEvent.objects.get().patient_id == queue.id


@pytest.mark.integration
@pytest.mark.django_db
def test_no_match_creates_exactly_one_provisional_patient_with_a_token():
    """No candidate: one provisional patient, one token, one log row.

    The unchanged ABD-008 fall-through — the branch the ambiguous case used to
    be mistaken for — pinned with row counts so a future refactor cannot
    silently change it into a queue entry.
    """
    _tenant_with_opd()

    response = _post(APIClient(), _payload(profile=_demographic_profile()))

    assert response.status_code == 200
    body = response.json()
    assert body["token"] is not None
    assert Patient.objects.count() == 1
    patient = Patient.objects.get()
    assert patient.id == uuid.UUID(body["patient_id"])
    assert patient.verification_status == "pending"
    assert ABHACallbackLog.objects.get().status == "ok"


@pytest.mark.integration
@pytest.mark.django_db
def test_ambiguous_queue_entry_is_visible_only_to_its_tenant():
    """ABD-009: the queue entry surfaces to tenant A's staff and never to tenant B.

    Denial by scoping, not by error type: tenant B's authenticated call is a
    well-formed 200 that simply has nothing in it. A 403 or 404 would confirm
    that some entry exists somewhere, and the queue points at PHI. The queue is
    also pinned to carry both statuses — ``pending`` registrations and the
    ``ambiguous`` ABDM rows live in one queue because the work is the same.
    """
    tenant_a, _, _ = _tenant_with_opd(slug="hospital-a", hip_id="hip-a")
    tenant_b, _, _ = _tenant_with_opd(slug="hospital-b", hip_id="hip-b")
    # Two front-desk-verified patients sharing name and birth year make the
    # profile ambiguous for tenant A.
    Patient.objects.create(
        tenant_id=tenant_a.id, uhid="UHID-QA-1", verification_status="verified",
        demographics={"name": "Queue Case", "gender": "M", "year_of_birth": 1990},
    )
    Patient.objects.create(
        tenant_id=tenant_a.id, uhid="UHID-QA-2", verification_status="verified",
        demographics={"name": "Queue Case", "gender": "M", "year_of_birth": 1990},
    )
    pending = Patient.objects.create(
        tenant_id=tenant_a.id, uhid="UHID-QA-3",
        demographics={"name": "Walk In", "gender": "F", "year_of_birth": 1960},
    )

    response = _post(
        APIClient(),
        _payload(
            facilityId="hip-a",
            profile=_demographic_profile(name="Queue Case", year=1990, gender="M"),
        ),
    )
    assert response.status_code == 200
    queue_id = response.json()["patient_id"]

    client_a = _make_queue_client(tenant_a, "clerk-a")
    response_a = client_a.get("/api/v1/patients/verification_queue/")
    assert response_a.status_code == 200
    assert {row["id"]: row["verification_status"] for row in response_a.data} == {
        queue_id: "ambiguous",
        str(pending.id): "pending",
    }

    client_b = _make_queue_client(tenant_b, "clerk-b")
    response_b = client_b.get("/api/v1/patients/verification_queue/")
    assert response_b.status_code == 200
    assert list(response_b.data) == []


@pytest.mark.integration
@pytest.mark.django_db
def test_replay_of_an_ambiguous_request_creates_no_second_queue_entry():
    """ABD-006: a replay returns the first acknowledgement and writes nothing new.

    The idempotency early-return precedes the atomic block, so a replayed
    ambiguous scan must not reach the queue-entry, consent or log writes at
    all — and the duplicate ack carries the original null token and the queue
    entry's id, so the gateway side sees a stable answer.
    """
    tenant, _, _ = _tenant_with_opd()
    for suffix in ("1", "2"):
        Patient.objects.create(
            tenant_id=tenant.id, uhid=f"UHID-REPLAY-{suffix}",
            demographics={"name": "Replay Case", "gender": "M", "year_of_birth": 1975},
        )
    client = APIClient()
    profile = _demographic_profile(name="Replay Case", year=1975, gender="M")

    first = _post(client, _payload(profile=profile))
    second = _post(client, _payload(profile=profile), count=2)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["token"] is None
    assert second.json()["patient_id"] == first.json()["patient_id"]

    assert Patient.objects.filter(verification_status="ambiguous").count() == 1
    assert Patient.objects.count() == 3
    assert ABHACallbackLog.objects.count() == 1
    assert ConsentEvent.objects.count() == 1
    assert Token.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_tampered_body_with_original_signature_is_rejected():
    """Mutating the body after signing must fail the HMAC (ABD-005).

    The view computes the digest over what it receives, so a body whose bytes
    differ from the ones that were signed can never match — even though the
    signature header is identical to a legitimate call's.
    """
    _tenant_with_opd()
    body, headers = _signed_request(_payload())
    tampered = body[:-1] + (b"x" if body[-1:] != b"x" else b"y")

    response = APIClient().post(
        CALLBACK_URL, tampered, content_type="application/json", **headers
    )

    assert response.status_code == 401
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
@override_settings(ABDM_CLIENT_SECRET="")
def test_unset_secret_fails_closed_outside_debug():
    """An unset shared secret must reject under non-DEBUG settings (ABD-005).

    The sandbox has no shared secret yet, so the fail-open path is DEBUG-only.
    If this returns 200 the endpoint would accept unsigned calls under
    production settings whenever the variable is missing.
    """
    _tenant_with_opd()
    body, _ = _signed_request(_payload())

    response = APIClient().post(
        CALLBACK_URL, body, content_type="application/json", **{"HTTP_X_ABDM_SIGNATURE": "deadbeef"}
    )

    assert response.status_code == 401
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_callback_is_idempotent_on_request_id():
    """A replayed request ID returns the first result, no second writes (ABD-006).

    Review Focus #3: the replay must return the *original* acknowledgement and
    must not create a second patient, token, or log row.
    """
    _tenant_with_opd()
    client = APIClient()

    first = _post(client, _payload())
    second = _post(client, _payload(), count=2)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["token"] == first.json()["token"]
    assert second.json()["request_id"] == first.json()["request_id"]
    assert second.json()["patient_id"] == first.json()["patient_id"]
    assert Token.objects.count() == 1
    assert ABHACallbackLog.objects.count() == 1
    assert Patient.objects.count() == 1


@pytest.mark.integration
@pytest.mark.django_db
def test_stale_timestamp_is_rejected():
    """Timestamps outside the skew window are refused (ABD-007)."""
    _tenant_with_opd()
    response = _post(APIClient(), _payload(timestamp="2020-01-01T00:00:00Z"))

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_payload_requires_request_id():
    """A missing requestId is a 400 ack, not a fabricated id (ABD-006, ABD-007).

    The old fallback invented ``secrets.token_uuid4().hex`` when requestId was
    absent, which defeated idempotency: the same scan replayed would be treated
    as fresh. A callback without a gateway request id is malformed, period.
    """
    _tenant_with_opd()
    response = _post(APIClient(), _payload(requestId=None))

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert "requestId" in response.json()["detail"]
    assert ABHACallbackLog.objects.count() == 0
    assert Token.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_payload_requires_timestamp():
    """A missing timestamp is a 400 ack, never a 500 (ABD-007)."""
    _tenant_with_opd()
    response = _post(APIClient(), _payload(timestamp=None))

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert "timestamp" in response.json()["detail"]
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_payload_requires_profile():
    """A missing profile is a 400 ack, never a write with a bogus profile (ABD-007).

    The old ``profile or payload`` fallback treated the whole callback as the
    profile, which would register a patient whose demographics came from
    transport fields. A profile-share callback without a profile is malformed.
    """
    _tenant_with_opd()
    response = _post(APIClient(), _payload(profile=None))

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert "profile" in response.json()["detail"]
    assert ABHACallbackLog.objects.count() == 0
    assert Token.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_unknown_hip_id_is_rejected():
    """A HIP ID belonging to no facility cannot resolve a tenant (ABD-004).

    A callback from an unknown HIP names a resource this installation does not
    own, so it is answered 404 (resource-not-found semantics) and writes
    nothing. Previously 400; the brief's ABD-004 pin makes the status explicit.
    """
    _tenant_with_opd()
    response = _post(APIClient(), _payload(facilityId="hip-not-registered"))

    assert response.status_code == 404
    assert response.json()["status"] == "rejected"
    assert response.json()["detail"] == "Unknown facility HIP ID"
    assert ABHACallbackLog.objects.count() == 0
    assert Token.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_scan_cannot_write_into_another_tenants_department():
    """A department UUID from another tenant refuses the call with 404 (ABD-013).

    The gateway is not trusted to name our departments. A supplied department id
    that is a valid UUID must resolve inside the scanned tenant; when it does
    not, the call is refused before any row is written — no patient, no token,
    no log. The old behaviour silently rerouted the scan to the first
    OPD-enabled department (a plausible misroute for a mis-issued QR code); the
    brief's ABD-013 pin makes a foreign department a hard refusal instead.
    """
    _tenant_with_opd(slug="hospital-a", hip_id="hip-a")
    _, _, department_b = _tenant_with_opd(slug="hospital-b", hip_id="hip-b")

    response = _post(
        APIClient(), _payload(facilityId="hip-a", departmentId=str(department_b.id))
    )

    assert response.status_code == 404
    assert response.json()["status"] == "rejected"
    assert Token.objects.count() == 0
    assert ABHACallbackLog.objects.count() == 0
    assert Patient.objects.count() == 0


def _canonical(profile):
    """The canonical JSON serialization ``hash_profile`` digests."""
    return json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()


@pytest.mark.integration
@pytest.mark.django_db
def test_successful_callback_records_one_consent_event():
    """One successful scan records exactly one consent event (ABD-011).

    The event used to be built as a dict inside the view and returned in the
    acknowledgement, which meant nothing downstream could ever prove consent was
    granted. Timestamp, source, purpose and facility are the four things the
    requirement names, so all four are pinned from the stored row.
    """
    tenant, facility, _ = _tenant_with_opd()
    response = _post(APIClient(), _payload())

    assert response.status_code == 200
    events = ConsentEvent.objects.all()
    assert events.count() == 1

    event = events.get()
    assert event.tenant_id == tenant.id
    assert event.patient_id == uuid.UUID(response.json()["patient_id"])
    assert event.request_id == "req-1"
    assert event.source_app == "ABDM"  # payload carries no sourceApp
    assert event.purpose == "registration"
    assert event.facility_id == facility.id
    assert event.granted_at is not None


@pytest.mark.integration
@pytest.mark.django_db
def test_consent_event_takes_the_gateways_source_app():
    """``sourceApp`` from the payload wins over the ABDM fallback (ABD-011).

    Consent provenance is the point of the record: a scan launched from another
    HIP's app has to be attributed to that app, not to "ABDM".
    """
    _tenant_with_opd()
    _post(APIClient(), _payload(sourceApp="NHA-Scan-and-Share"))

    assert ConsentEvent.objects.get().source_app == "NHA-Scan-and-Share"


@pytest.mark.integration
@pytest.mark.django_db
def test_consent_event_ties_itself_to_the_payload_with_a_hash():
    """``raw_profile_hash`` is the one-way SHA-256 of the shared profile.

    The digest lets an auditor confirm a consent record belongs to the payload
    in hand without the table holding any of it. Canonical serialization is
    asserted too: key order in the gateway's JSON must not change the digest.
    """
    profile = {"abhaNumber": "123456789012", "demographics": {"yearOfBirth": 1984}}
    _tenant_with_opd()
    _post(APIClient(), _payload(profile=profile))

    event = ConsentEvent.objects.get()
    assert event.raw_profile_hash == hashlib.sha256(_canonical(profile)).hexdigest()
    assert len(event.raw_profile_hash) == 64


@pytest.mark.integration
@pytest.mark.django_db
def test_consent_event_row_carries_no_profile_data():
    """Data minimisation: the consent table holds no PHI (ABD-011, §8.4).

    Asserted two ways, because either alone is weak. The stored row is dumped
    field by field and no profile substring may appear anywhere in it — the
    patient's name and ABHA number are in the posted profile, so a copy of the
    profile would show up here. And the column set itself is pinned, so a future
    migration cannot quietly add a ``name`` or ``abha_number`` column and pass a
    test that only greps the values.
    """
    profile = {
        "abhaNumber": "123456789012",
        "demographics": {"name": "Asha Verma", "yearOfBirth": 1984, "gender": "F"},
    }
    _tenant_with_opd()
    _post(APIClient(), _payload(profile=profile))

    row = ConsentEvent.objects.values().get()
    assert set(row) == {
        "id",
        "tenant_id",
        "patient_id",
        "request_id",
        "source_app",
        "purpose",
        "facility_id",
        "granted_at",
        "raw_profile_hash",
    }

    dumped = json.dumps(row, default=str)
    for profile_data in ("Asha Verma", "123456789012", "abhaNumber", "demographics"):
        assert profile_data not in dumped


@pytest.mark.integration
@pytest.mark.django_db
def test_replay_creates_no_second_consent_event():
    """A replayed request ID records no second consent event (ABD-006/ABD-011).

    Idempotency is enforced by the early return before the atomic block, so a
    replay must not reach the consent write at all: two consent events for one
    scan would be two records of the same grant, which a DPDP audit cannot
    reconcile.
    """
    _tenant_with_opd()
    client = APIClient()

    first = _post(client, _payload())
    _post(client, _payload(), count=2)

    assert first.status_code == 200
    assert ConsentEvent.objects.count() == 1
    assert ABHACallbackLog.objects.count() == 1


@pytest.mark.integration
@pytest.mark.django_db
def test_consent_event_rolls_back_with_the_rest_of_the_write(monkeypatch):
    """A consent record must never outlive the transaction that created it.

    The failure is injected *after* the consent event would have been written
    (the link token is minted last), so a consent row surviving it would be a
    dangling DPDP record naming a patient that was never registered.
    """
    _tenant_with_opd()

    def _explode(*args, **kwargs):
        raise RuntimeError("link token minting failed")

    monkeypatch.setattr("apps.abdm_gateway.views.secrets.token_urlsafe", _explode)

    with pytest.raises(RuntimeError, match="link token minting failed"):
        _post(APIClient(), _payload())

    assert ConsentEvent.objects.count() == 0
    assert Patient.objects.count() == 0
    assert ABHACallbackLog.objects.count() == 0
    assert Token.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_ack_stops_returning_the_plaintext_link_token():
    """ABD-012: the link token is stored sealed, never echoed to the gateway.

    It exists for care-context linking, which the gateway does not need the
    value for. Returning it put a bearer-style credential in an acknowledgement
    that logs, proxies and browser tooling all see.
    """
    _tenant_with_opd()
    response = _post(APIClient(), _payload())

    body = response.json()
    assert body["status"] == "ok"
    assert "link_token" not in body
    # The consent event stays in the acknowledgement — it carries no PHI.
    assert body["consent_event"]["purpose"] == "registration"
    assert body["consent_event"]["source_app"] == "ABDM"


@pytest.mark.integration
@pytest.mark.django_db
def test_link_token_is_stored_encrypted_not_in_clear():
    """The stored link token is a ``v1:`` AES-GCM token, not the plaintext.

    Decrypted under the test passphrase it yields a 43-character
    ``token_urlsafe(32)`` value — the shape the view mints — which is what
    proves the column holds the sealed link token and not some other secret.
    """
    _tenant_with_opd()
    _post(APIClient(), _payload())

    stored = ABHACallbackLog.objects.values_list("link_token_enc", flat=True).get()
    assert stored is not None
    assert stored.startswith("v1:")

    aes_key, _ = derive_keys(settings.PATIENT_FIELDS_KEY)
    plaintext = decrypt(stored, key=aes_key)
    assert len(plaintext) == 43  # secrets.token_urlsafe(32)
    assert stored != plaintext


@pytest.mark.integration
def test_health_probe_route_name_is_stable():
    """Guard against a router rename silently breaking monitoring."""
    assert reverse("common:health") == "/api/v1/health/"
