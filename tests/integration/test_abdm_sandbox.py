"""ABD-017: the ABDM profile-share test case, replayed against our own endpoint.

The SRS requirement reads "the system shall pass the ABDM profile-share test
case in sandbox for each supported API version". This module is the replay half
of that requirement: it signs a profile-share callback per supported API
version, posts it to ``/api/v1/abdm-callbacks/`` exactly as the ABDM gateway
does, and pins the three things the test case is judged on — the
acknowledgement's shape, the consent row behind it (ABD-011) and the OPD token
issued from it (ABD-010).

**A skip is not a verification.** The module is gated on ``ABDM_SANDBOX_RUN``
and every case is skipped without it, so a skipped case has proved nothing about
the sandbox. The evidence ABD-017 needs is a run recorded in the Run log of
``docs/abdm-sandbox-runbook.md``, and only a run that reaches the *live* sandbox
counts: this replay is deliberately hermetic. It runs against the Django test
database and our own endpoint, never opening a connection to ABDM — which is
what makes it safe to run in CI, and also what makes it insufficient on its own.
It proves our side of the exchange, not the sandbox's.

What the replay does cover is the contract the gateway exercises on the way in:
the HMAC over the raw body (ABD-005), the mandatory keys and timestamp skew
(ABD-007), tenant resolution from the facility's HIP ID (ABD-004), the
idempotency ledger (ABD-006), the ABHA and demographic match branches
(ABD-008/ABD-009), the token (ABD-010), the consent record (ABD-011) and the
sealed link token (ABD-012).
"""
import os
import uuid
from datetime import datetime

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

# ``test_abdm_callback`` is the file that pins the callback's behaviour, so the
# signing and seeding helpers are imported from it rather than restated: a
# replay that signed its bytes by a different rule than the pinned tests would
# prove nothing about the endpoint the sandbox actually calls. The import works
# because both modules live in this directory, which pytest puts on ``sys.path``
# for whichever of the two it imports.
from test_abdm_callback import _payload, _post, _tenant_with_opd

from apps.abdm_gateway.client import require_sandbox_base_url
from apps.abdm_gateway.consent import hash_profile
from apps.abdm_gateway.models import ABHACallbackLog, ConsentEvent
from apps.opd.models import Token

#: The ABDM profile-share API versions this replay covers. Architecture doc
#: section 8.2 records v1.0 and v3 paths coexisting — "the ABHA app was still
#: calling the older flow while v3 existed" — and requires the ``abdm-gateway``
#: module to sit behind an adapter that supports both, so those two are what
#: the repo's documented payload contract covers. The sandbox's *authoritative*
#: version list cannot be resolved offline and is deliberately not invented
#: here; the runbook (`docs/abdm-sandbox-runbook.md`) states that it must be
#: confirmed against ABDM's sandbox documentation before this count is claimed
#: as complete coverage.
API_VERSIONS = ("v1.0", "v3")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("ABDM_SANDBX_RUN"),
        reason=(
            "set ABDM_SANDBOX_RUN=1 to run the ABD-017 profile-share replay, "
            "with ABDM_CLIENT_SECRET exported; the run must then be recorded "
            "in the Run log of docs/abdm-sandbox-runbook.md — a skip is not a "
            "verification and does not count towards ABD-017"
        ),
    ),
]


def _sandbox_secret() -> str:
    """The shared secret this replay signs with (ABD-005).

    Precedence: ``ABDM_CLIENT_SECRET`` from the environment wins, because a
    recorded sandbox run has to sign with the credential the *gateway* signs
    with — a replay signed with anything else would be refused by the very
    check it exists to exercise, and the failure would look like an endpoint
    defect. The fallback is ``settings.ABDM_CLIENT_SECRET``, which
    ``config/settings/test.py`` already populated from that same environment
    variable with a deterministic literal when the environment carried none, so
    the gated run stays reproducible without credentials and never has to guess
    a real one. Read through ``os.environ`` first rather than through settings
    alone so the precedence is visible here instead of inherited from an import
    side effect.
    """
    return os.environ.get("ABDM_CLIENT_SECRET") or settings.ABDM_CLIENT_SECRET


def _require_sandbox_shaped_configuration() -> str:
    """Re-assert Task 14's sandbox-only gate for the recorded run.

    ``config/settings/base.py`` runs :func:`require_sandbox_base_url` at import
    time, so a base URL that reached settings is already https on an ``sbx``
    host. Re-running the predicate here pins the *coupling* rather than the
    value: if the import-time gate is ever widened or dropped, this replay fails
    instead of quietly recording a run against a production-shaped ABDM
    endpoint. Returns ``""`` when no outbound base URL is configured, which is
    the normal case for this replay — it posts to our own endpoint and needs no
    outbound adapter.
    """
    base_url = settings.ABDM_SANDBX_BASE_URL
    return require_sandbox_base_url(base_url) if base_url else ""


def _profile_share_payload(api_version: str, hip_id: str) -> dict:
    """The profile-share callback the gateway posts after a QR scan.

    Built from ``test_abdm_callback._payload`` so the replay carries exactly the
    shape that file pins: ``requestId``, ``timestamp`` and ``profile`` are
    mandatory (ABD-007), ``facilityId`` names the facility's HIP ID (ABD-004),
    and the profile carries the ABHA number with demographics. ``sourceApp`` is
    set so the consent row's provenance is the payload's own rather than the
    ``"ABDM"`` fallback (ABD-011).

    The gateway request id embeds the API version only. This replay declares no
    ``apiVersion``, so since INT-002 it is answered in the default ``v2`` shape
    — the shape this endpoint returned before version support existed — whatever
    label the request id carries. (That is also what makes each parametrised
    case a *fresh* scan rather than a replay of the previous one, which
    idempotency would answer with the first acknowledgement, ABD-006.) A
    version-matched request id that a sandbox operator sees in the callback
    ledger therefore identifies the flow the gateway used.

    Note that ``v1.0`` and ``v3`` here are *replay labels*, not the adapter's
    vocabulary: the versions the adapter serves are ``v2`` and ``v3`` (see
    ``SUPPORTED_API_VERSIONS`` in ``apps.abdm_gateway.client``). Were this replay
    to declare one, ``v1.0`` would be served as an accepted **alias** of the
    ``v2`` shape (``API_VERSION_ALIASES``) and ``v3`` in its own shape; an
    unrecognised label is served in the default ``v2`` shape with a warning, and
    only a *malformed* declaration — a list, an object or a number — is refused
    with 422. No version string is ever refused.
    """
    return _payload(
        requestId=f"sbx-profile-share-{api_version}",
        facilityId=hip_id,
        sourceApp=f"abdm-sandbox-replay-{api_version}",
    )


@pytest.mark.integration
@pytest.mark.django_db
@pytest.mark.parametrize("api_version", API_VERSIONS, ids=API_VERSIONS)
def test_profile_share_replay_per_supported_api_version(api_version):
    """Replay one profile share per supported API version (ABD-017).

    Seeded the way the callback suite seeds: one tenant, one facility carrying
    the HIP ID the gateway names, one OPD-enabled department to hold the token.
    That is the entire setup the real flow needs, which is the point — a replay
    that required fixtures the gateway never exercises would prove something
    about the fixture.

    The three assertion groups are the test case's own scorecard:

    * the acknowledgement answers ``ok`` with a request id, a token id, a
      patient id and the consent provenance the gateway needs back — and no
      link token, the one credential an ack must never echo (ABD-012);
    * exactly one consent row exists for the tenant, carrying the payload's own
      source app, the purpose and the facility (ABD-011);
    * one OPD token was issued against the patient the acknowledgement names
      (ABD-010).
    """
    _require_sandbox_shaped_configuration()
    secret = _sandbox_secret()
    slug = f"abdm-sandbox-{api_version.replace('.', '-')}"
    hip_id = f"hip-sbx-{api_version}"
    tenant, facility, department = _tenant_with_opd(slug=slug, hip_id=hip_id)
    payload = _profile_share_payload(api_version, hip_id=hip_id)

    response = _post(APIClient(), payload, secret=secret)

    assert response.status_code == 200
    body = response.json()

    # (a) The acknowledgement shape the gateway is contractually shown.
    assert body["status"] == "ok"
    assert body["request_id"] == payload["requestId"]
    token_id = uuid.UUID(body["token"])
    patient_id = uuid.UUID(body["patient_id"])
    consent_event = body["consent_event"]
    # The exact key set rather than a subset check: an ack that started echoing
    # ``raw_profile_hash`` or a patient attribute would otherwise pass here, and
    # the acknowledgement is the part of this flow every proxy and access log
    # sees. ``timestamp`` is pinned as a real grant time immediately below; it
    # is echoed from its own key here so the comparison still catches a renamed
    # or an extra field.
    assert consent_event == {
        "timestamp": consent_event["timestamp"],
        "source_app": payload["sourceApp"],
        "purpose": "registration",
        "facility_id": str(facility.id),
    }
    # The echoed grant time is the grant time, not a placeholder: outside the
    # skew window the gateway would discard an acknowledgement it cannot place
    # in the scan's own timeline (ABD-007).
    granted_at = datetime.fromisoformat(consent_event["timestamp"])
    ack_skew = abs((timezone.now() - granted_at).total_seconds())
    assert ack_skew <= settings.ABDM_MAX_SKEW_SECONDS

    # (b) One consent row for this tenant, carrying the payload's provenance.
    events = ConsentEvent.objects.filter(tenant_id=tenant.id)
    assert events.count() == 1
    event = events.get()
    assert event.patient_id == patient_id
    assert event.request_id == payload["requestId"]
    assert event.source_app == payload["sourceApp"]
    assert event.purpose == "registration"
    assert event.facility_id == facility.id
    assert event.granted_at is not None
    # T16's one-way tie: the row proves it belongs to *this* payload without
    # holding any of it (data minimisation, section 8.4).
    assert event.raw_profile_hash == hash_profile(payload["profile"])

    # (c) The OPD token the patient walks to the counter with.
    token = Token.objects.get(id=token_id)
    assert token.patient_id == patient_id
    assert token.tenant_id == tenant.id
    assert token.department_id == department.id
    assert token.status == "waiting"
    assert Token.objects.count() == 1

    # The ledger behind the acknowledgement: one row, matched, sealed link
    # token, and nothing echoed back to the gateway (ABD-006, ABD-012).
    # ``token_issued`` is a CharField, so it is compared as the string the ack
    # carried — comparing it to the UUID would pass on coercion alone and prove
    # nothing about which token the ledger names.
    log = ABHACallbackLog.objects.get(request_id=payload["requestId"])
    assert log.tenant_id == tenant.id
    assert log.status == "ok"
    assert log.token_issued == body["token"]
    assert log.link_token_enc is not None and log.link_token_enc.startswith("v1:")
    assert "link_token" not in body
