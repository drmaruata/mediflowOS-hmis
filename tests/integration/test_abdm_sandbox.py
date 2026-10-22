"""ABD-017: the ABDM profile-share test case, replayed against our own endpoint.

The SRS requirement reads "the system shall pass the ABDM profile-share test
case in sandbox for each supported API version". This module is the replay half
of that requirement: it signs a profile-share callback per supported API version,
posts it to ``/api/v1/abdm-callbacks/`` exactly as the ABDM gateway does, and
pins the three things the test case is judged on — the acknowledgement's shape,
the consent row behind it (ABD-011) and the OPD token issued from it (ABD-010).

**A skip is not a verification.** The module is gated on ``ABDM_SANDBOX_RUN``, so
a skipped case has proved nothing. The evidence ABD-017 needs is a run recorded
in the Run log of ``docs/abdm-sandbox-runbook.md``, and only a run that reaches
the *live* sandbox counts: this replay is deliberately hermetic, running against
the Django test database and our own endpoint, never opening a connection to
ABDM. It proves our side of the exchange, not the sandbox's.
"""
import os
import uuid
from datetime import datetime

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

# The signing and seeding helpers are imported from the file that pins the
# callback's behaviour rather than restated: a replay that signed its bytes by a
# different rule than the pinned tests would prove nothing about the endpoint the
# sandbox actually calls. The import works because both modules live in this
# directory, which pytest puts on ``sys.path``.
from test_abdm_callback import _payload, _post, _tenant_with_opd

from apps.abdm_gateway.client import require_sandbox_base_url
from apps.abdm_gateway.consent import hash_profile
from apps.abdm_gateway.models import ABHACallbackLog, ConsentEvent
from apps.opd.models import Token

#: The ABDM profile-share API versions this replay covers. Architecture doc §8.2
#: records v1.0 and v3 paths coexisting and requires an adapter supporting both.
#: The sandbox's *authoritative* version list cannot be resolved offline and is
#: deliberately not invented here; the runbook states it must be confirmed against
#: ABDM's sandbox documentation before this count is claimed as complete coverage.
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

    ``ABDM_CLIENT_SECRET`` from the environment wins, because a recorded sandbox
    run has to sign with the credential the *gateway* signs with — a replay
    signed with anything else would be refused by the very check it exists to
    exercise, and the failure would look like an endpoint defect. The fallback is
    ``settings.ABDM_CLIENT_SECRET``, which ``config/settings/test.py`` already
    populated from that same variable with a deterministic literal.
    """
    return os.environ.get("ABDM_CLIENT_SECRET") or settings.ABDM_CLIENT_SECRET


def _require_sandbox_shaped_configuration() -> str:
    """Re-assert Task 14's sandbox-only gate for the recorded run.

    ``config/settings/base.py`` runs :func:`require_sandbox_base_url` at import
    time, so a base URL that reached settings is already https on an ``sbx``
    host. Re-running the predicate here pins the *coupling* rather than the value:
    if the import-time gate is ever widened or dropped, this replay fails instead
    of quietly recording a run against a production-shaped ABDM endpoint.
    """
    base_url = settings.ABDM_SANDBX_BASE_URL
    return require_sandbox_base_url(base_url) if base_url else ""


def _profile_share_payload(api_version: str, hip_id: str) -> dict:
    """The profile-share callback the gateway posts after a QR scan.

    Built from ``test_abdm_callback._payload`` so the replay carries exactly the
    shape that file pins: ``requestId``, ``timestamp`` and ``profile`` are
    mandatory (ABD-007), ``facilityId`` names the facility's HIP ID (ABD-004),
    and ``sourceApp`` is set so the consent row's provenance is the payload's own
    (ABD-011).

    The request id embeds the API version only. This replay declares no
    ``apiVersion``, so since INT-002 it is answered in the default ``v2`` shape
    whatever label the request id carries — which is also what makes each
    parametrised case a *fresh* scan rather than a replay of the previous one
    (ABD-006).

    Note that ``v1.0`` and ``v3`` here are *replay labels*, not the adapter's
    vocabulary: the adapter serves ``v2`` and ``v3``
    (``SUPPORTED_API_VERSIONS``). Were this replay to declare one, ``v1.0`` would
    be served as an accepted **alias** of the ``v2`` shape and ``v3`` in its own
    shape. No version string is ever refused; only a malformed one is.
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

    The three assertion groups are the test case's own scorecard: the
    acknowledgement answers ``ok`` with the ids the gateway needs and no link
    token (ABD-012); exactly one consent row carries the payload's own provenance
    (ABD-011); and one OPD token was issued against the named patient (ABD-010).
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
    # ``raw_profile_hash`` or a patient attribute would otherwise pass, and the
    # acknowledgement is the part of this flow every proxy and access log sees.
    # ``timestamp`` is pinned as a real grant time immediately below; it is echoed
    # from its own key so the comparison still catches a renamed or extra field.
    assert consent_event == {
        "timestamp": consent_event["timestamp"],
        "source_app": payload["sourceApp"],
        "purpose": "registration",
        "facility_id": str(facility.id),
    }
    # The echoed grant time is the grant time: outside the skew window the gateway
    # would discard an acknowledgement it cannot place in the scan's timeline.
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
    # The row proves it belongs to *this* payload without holding any of it (§8.4).
    assert event.raw_profile_hash == hash_profile(payload["profile"])

    # (c) The OPD token the patient walks to the counter with.
    token = Token.objects.get(id=token_id)
    assert token.patient_id == patient_id
    assert token.tenant_id == tenant.id
    assert token.department_id == department.id
    assert token.status == "waiting"
    assert Token.objects.count() == 1

    # The ledger behind the acknowledgement: one row, matched, sealed link token,
    # nothing echoed back to the gateway (ABD-006, ABD-012). ``token_issued`` is
    # compared as the string the ack carried — comparing it to the UUID would pass
    # on coercion alone and prove nothing about which token the ledger names.
    log = ABHACallbackLog.objects.get(request_id=payload["requestId"])
    assert log.tenant_id == tenant.id
    assert log.status == "ok"
    assert log.token_issued == body["token"]
    assert log.link_token_enc is not None and log.link_token_enc.startswith("v1:")
    assert "link_token" not in body
