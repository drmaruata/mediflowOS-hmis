"""ABDM gateway views — Scan and Share callback processing.

Architecture doc section 8.4 requires:
1. Authenticate every gateway call per ABDM specification
2. Resolve tenant from HIP ID, then set RLS context
3. Idempotency on gateway request ID
4. Strict timestamp and payload validation
5. Match by ABHA number, then demographics — a multi-candidate match queues
   for human verification instead of guessing (ABD-009)
6. Issue OPD token; heavy work async
7. Record consent event; store link token encrypted

This endpoint is intentionally anonymous (gateway carries no user JWT).
"""
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone as dt_tz

from django.conf import settings
from django.db import transaction
from django.http.request import RawPostDataException
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from common.tenant import bind_tenant_session
from common.throttling import AbdmHipThrottle
from .consent import hash_profile, record_consent_event, store_link_token
from .models import ABHACallbackLog
from .serializers import ABHACallbackAckSerializer, ABHACallbackSerializer
from .services import resolve_profile

logger = logging.getLogger(__name__)


class _NoOpdDepartment(Exception):
    """Raised when the tenant has no department able to hold an OPD token."""


class _ForeignDepartment(Exception):
    """Raised when the gateway supplies a department that is not ours.

    Kept distinct from ``_NoOpdDepartment`` so the view can answer a foreign
    id with 404 (the named department does not exist *for this tenant*) rather
    than 409 (this tenant has no OPD department at all).
    """


class ABHACallbackViewSet(viewsets.ViewSet):
    """ABDM profile-share callback endpoint (ABD-003 to ABD-014)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [AbdmHipThrottle]
    serializer_class = ABHACallbackSerializer

    # --- internal helpers -------------------------------------------------

    def _validate_timestamp(self, payload: dict) -> bool:
        """Reject callbacks with timestamps outside the tolerance window."""
        ts = payload.get("timestamp") or payload.get("requestedAt")
        if not ts:
            return False
        try:
            if isinstance(ts, (int, float)):
                callback_dt = datetime.fromtimestamp(ts, tz=dt_tz.utc)
            else:
                callback_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, OSError, OverflowError):
            return False
        now = timezone.now()
        delta = abs((now - callback_dt).total_seconds())
        # Window per the ABDM spec, configurable because a gateway whose clock
        # drifts would otherwise have every callback refused. Read through
        # settings so a test can narrow it.
        return delta <= settings.ABDM_MAX_SKEW_SECONDS

    def _validate_payload_schema(self, payload: dict) -> str | None:
        """Check the mandatory callback keys, naming the first one missing.

        Returns ``None`` when the payload is well formed, otherwise the field
        name that is absent or empty. A malformed callback used to be patched
        over — a fabricated ``requestId`` defeated idempotency (ABD-006) and
        ``profile or payload`` registered patients from transport fields
        (ABD-007) — so the key that is missing is reported instead.
        """
        if not isinstance(payload, dict):
            return "payload"
        for key in ("requestId", "timestamp", "profile"):
            if not payload.get(key):
                return key
        return None

    def _resolve_tenant_from_hip(self, hip_id: str):
        """Resolve tenant from the facility's ABDM HIP ID (ABD-004)."""
        from apps.identity_tenancy.models import Facility
        try:
            facility = Facility.objects.get(abdm_hip_id=hip_id)
        except Facility.DoesNotExist:
            return None
        return str(facility.tenant_id), str(facility.id)

    def _authenticate_call(self, request) -> bool:
        """Verify the gateway's HMAC-SHA256 signature over the raw body (ABD-005).

        The gateway signs the exact bytes it posts with
        ``HMAC-SHA256(ABDM_CLIENT_SECRET)`` and sends the hex digest in
        ``X-ABDM-Signature``; this recomputes the digest over the bytes
        actually received and compares with :func:`hmac.compare_digest`. The
        raw body is what gets signed, never a re-serialization of the parsed
        payload: key order and separators are the client's choice, so parsing
        and dumping again would break the digest of a legitimate call.

        Presence-only headers used to authenticate here — any non-empty
        ``X-ABDM-Signature``, ``X-Authorization`` or ``Bearer`` token was
        accepted, which proved nothing and let any caller write into a
        tenant. Only a matching digest does now.

        The ABDM sandbox issues no shared secret yet, so an empty
        ``ABDM_CLIENT_SECRET`` is the local-development case: under ``DEBUG``
        the call is accepted with a warning (there is no secret to verify
        against), and outside it the call is refused. Read through ``settings``
        rather than at import time so tests can flip both values.

        The secret and the signature are never logged.
        """
        signature = request.headers.get("X-ABDM-Signature") or ""
        if not signature:
            # DEBUG only excuses an *unverifiable* signature, never a missing
            # one: a caller that sends no credential at all is refused
            # regardless of environment.
            return False

        secret = settings.ABDM_CLIENT_SECRET
        if not secret:
            if not settings.DEBUG:
                logger.warning(
                    "ABDM callback refused: ABDM_CLIENT_SECRET is unset and "
                    "DEBUG is off, so no signature can be verified"
                )
                return False
            logger.warning(
                "ABDM callback: ABDM_CLIENT_SECRET is unset, so the "
                "X-ABDM-Signature cannot be verified — accepting because "
                "DEBUG is on"
            )
            return True

        try:
            body = request.body
        except RawPostDataException:
            # Something upstream already consumed the stream (Django raises
            # this rather than returning a truncated body), so there is
            # nothing to verify against. Refuse rather than guess.
            logger.warning("ABDM callback refused: request body is unreadable")
            return False

        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        # Compared as bytes, not str: the header value is attacker-controlled
        # and a non-ASCII one makes hmac.compare_digest raise TypeError
        # (a 500) instead of simply failing to match.
        return hmac.compare_digest(expected.encode("ascii"), signature.encode("utf-8"))

    def _idempotent_check(self, request_id: str, tenant_id: str):
        """Check for a duplicate request ID (ABD-006)."""
        try:
            return ABHACallbackLog.objects.get(request_id=request_id, tenant_id=tenant_id)
        except ABHACallbackLog.DoesNotExist:
            return None

    def _resolve_department(self, raw_department_id):
        """Resolve a department the gateway supplied to a real, local department.

        The gateway is not trusted to name our departments: it sends whatever
        the scanning facility had configured. An id that is absent, blank or
        not a UUID is unusable rather than hostile, so it falls back to the
        facility's first OPD-enabled department with a warning — a scan for a
        real patient should not be lost to a QR code minted without one.

        An id that *is* a well-formed UUID but resolves to no department of this
        tenant is a different case: it names a department that exists, just not
        here. Silently rerouting that scan to an unrelated department would
        queue the patient for the wrong service and put the resulting token in
        the wrong series, so it raises instead.

        Must be called with the tenant session bound: the fallback lookup is
        row-level-security scoped and returns nothing without it.
        """
        from apps.identity_tenancy.models import Department

        if raw_department_id:
            try:
                candidate = uuid.UUID(str(raw_department_id))
            except (ValueError, AttributeError, TypeError):
                logger.warning("ABDM callback: department_id %r is not a UUID", raw_department_id)
                candidate = None
            if candidate is not None:
                # Scoped to this tenant so one facility cannot issue tokens
                # into another hospital's department.
                department = Department.objects.filter(
                    tenant_id=self._tenant_id, id=candidate
                ).first()
                if department is not None:
                    return department
                raise _ForeignDepartment(str(candidate))

        return (
            Department.objects.filter(tenant_id=self._tenant_id, opd_enabled=True)
            .order_by("name")
            .first()
        )

    def _generate_abdm_uhid(self) -> str:
        """Mint an ``ABDM``-prefixed UHID that is free in this tenant.

        Shared by the provisional and the ambiguous queue entry because the
        UHID must exist before the row does (it is NOT NULL) and a repeat would
        violate ``(tenant_id, uhid)``. The ``ABDM`` prefix keeps gateway-minted
        rows visibly distinct from the counter's ``UHID-`` series, which is what
        a clerk sees when a queue entry has to be resolved by hand.
        """
        from apps.patient_registry.models import Patient

        while True:
            uhid = f"ABDM{uuid.uuid4().hex[:12].upper()}"
            if not Patient.objects.filter(tenant_id=self._tenant_id, uhid=uhid).exists():
                return uhid

    def _create_provisional_patient(self, profile: dict):
        """Create a pending patient record for an unmatched ABDM profile (REG-004).

        The patient is registered as ``pending`` verification rather than
        ``verified``: the demographics arrived over the gateway and nobody at
        the front desk has confirmed them against an identity document, so the
        verification queue is the only honest state to record.
        """
        from apps.patient_registry.models import Patient

        demographics = profile.get("demographics") or {}
        abha_number = profile.get("abhaNumber") or profile.get("healthId")

        return Patient.objects.create(
            tenant_id=self._tenant_id,
            uhid=self._generate_abdm_uhid(),
            abha_number=abha_number or None,
            verification_status="pending",
            demographics={
                "name": demographics.get("name") or profile.get("name", ""),
                "gender": demographics.get("gender") or profile.get("gender"),
                "yearOfBirth": demographics.get("yearOfBirth") or profile.get("yearOfBirth"),
            },
            consent_flags={"abdm_scan_and_share": True},
        )

    def _create_ambiguous_queue_entry(self, profile: dict):
        """Register a multi-candidate scan as one ambiguous queue entry (ABD-009).

        Several registrations fit the scan equally well, and linking any one of
        them is a coin toss between real patients — so nothing is linked. One
        row is written with ``verification_status="ambiguous"``: the front desk
        gets a queue entry to resolve, and the acknowledgement still carries its
        id so the gateway can tell the scanning patient what happened. The
        candidates a clerk must choose between live on the log row
        (``match_candidates``), not here: this patient table must not become a
        place where one patient's scan points at other patients beyond the ids
        needed to resolve it.

        Same shape as the provisional patient (REG-004) apart from the status —
        the demographics are unverified gateway data either way.
        """
        from apps.patient_registry.models import Patient

        demographics = profile.get("demographics") or {}
        abha_number = profile.get("abhaNumber") or profile.get("healthId")

        return Patient.objects.create(
            tenant_id=self._tenant_id,
            uhid=self._generate_abdm_uhid(),
            abha_number=abha_number or None,
            verification_status="ambiguous",
            demographics={
                "name": demographics.get("name") or profile.get("name", ""),
                "gender": demographics.get("gender") or profile.get("gender"),
                "yearOfBirth": demographics.get("yearOfBirth") or profile.get("yearOfBirth"),
            },
            consent_flags={"abdm_scan_and_share": True},
        )

    def _issue_token(self, department, patient_id) -> str:
        """Issue an OPD token for the intake point (ABD-010).

        ``patient_id`` is required because ``opd.Token.patient_id`` is NOT NULL;
        the caller creates the patient when the profile does not match an
        existing record.

        The series and number come from the shared token-series service
        (REG-010): a pre-configured TokenSeries prefix for the department wins
        over the old inline ``QR-<uuid>`` naming, and the counter is safe
        under concurrent scans.
        """
        from apps.opd.models import Token
        from apps.opd.services import next_token_number

        if department is None:
            raise _NoOpdDepartment()

        prefix, number = next_token_number(
            tenant_id=self._tenant_id,
            facility_id=department.facility_id,
            department_id=department.id,
        )
        token = Token.objects.create(
            tenant_id=self._tenant_id,
            patient_id=patient_id,
            department_id=department.id,
            series=prefix,
            number=number,
            status="waiting",
        )
        return str(token.id)

    # --- main entry point -------------------------------------------------

    def create(self, request):
        payload = request.data

        # ABD-005: authenticate the gateway call
        if not self._authenticate_call(request):
            logger.warning("ABDM callback rejected: unauthenticated call from %s", request.META.get("REMOTE_ADDR"))
            return Response(
                {"status": "rejected", "detail": "Authentication failed"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # ABD-007: required keys, before any of them is used or defaulted
        missing_key = self._validate_payload_schema(payload)
        if missing_key is not None:
            return Response(
                {
                    "status": "rejected",
                    "detail": f"Missing required callback field: {missing_key}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ABD-007: validate timestamp
        if not self._validate_timestamp(payload):
            return Response(
                {"status": "rejected", "detail": "Invalid or stale timestamp"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Extract key fields. The schema check above guarantees requestId and
        # profile exist; neither is defaulted any further.
        request_id = payload["requestId"]
        hip_id = payload.get("facilityId") or payload.get("hipId") or ""
        profile = payload["profile"]

        # ABD-004: resolve tenant from HIP ID
        tenant_facility = self._resolve_tenant_from_hip(hip_id)
        if not tenant_facility:
            # Not found rather than malformed: the gateway named a facility
            # this installation does not host, so there is nothing to route
            # the callback to. 400 implied the request itself was wrong.
            return Response(
                {"status": "rejected", "detail": "Unknown facility HIP ID"},
                status=status.HTTP_404_NOT_FOUND,
            )
        tenant_id, facility_id = tenant_facility

        # ABD-006: idempotency check
        existing = self._idempotent_check(request_id, tenant_id)
        if existing:
            return Response(
                {
                    "status": "duplicate",
                    "detail": "This request was already processed",
                    "request_id": request_id,
                    "token": existing.token_issued,
                    "patient_id": str(existing.matched_patient_id) if existing.matched_patient_id else None,
                },
                status=status.HTTP_200_OK,
            )

        # Bind tenant context inside the transaction (ABD-004, RLS)
        self._tenant_id = tenant_id
        self._facility_id = facility_id

        with transaction.atomic():
            bind_tenant_session(tenant_id, facility_id)

            # ABD-010: resolve the department the gateway named *before* the
            # patient is matched or registered. A refusal from here returns a
            # response, and returning from inside atomic() commits the block,
            # so nothing may have been written yet for the commit to keep.
            try:
                department = self._resolve_department(
                    payload.get("departmentId") or payload.get("intakePointId")
                )
            except _ForeignDepartment:
                logger.warning(
                    "ABDM callback: supplied department is not part of tenant %s",
                    tenant_id,
                )
                return Response(
                    {
                        "status": "rejected",
                        "detail": "Supplied department is not part of this facility",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            # ABD-008/009: resolve the shared profile — an exact ABHA match, a
            # single demographic candidate, several (ambiguous) or none.
            resolution = resolve_profile(profile=profile, tenant_id=tenant_id)

            if resolution.kind == "candidates":
                # ABD-009: several registrations fit this scan, so none of them
                # is linked. Exactly one queue entry is created, the consent is
                # still recorded, and the callback is acknowledged 200 with a
                # null token — the scan was received and the consent honoured,
                # but identity resolution is now queued work for the front desk.
                patient = self._create_ambiguous_queue_entry(profile)

                # ABD-011: the consent still happened — the patient scanned and
                # shared at the counter — so it is still recorded, naming the
                # queue entry this scan produced. Deferring the record would
                # leave a real grant unlogged because identity work was
                # outstanding; only the identity resolution is queued.
                consent_event = record_consent_event(
                    tenant_id=tenant_id,
                    patient_id=patient.id,
                    request_id=request_id,
                    source_app=payload.get("sourceApp") or "ABDM",
                    purpose="registration",
                    facility_id=facility_id,
                    raw_profile_hash=hash_profile(profile),
                )

                log = ABHACallbackLog.objects.create(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    facility_abdm_id=hip_id,
                    ip=request.META.get("REMOTE_ADDR"),
                    profile=json.dumps(profile)[:4000],  # truncate large payloads
                    matched_patient_id=patient.id,
                    token_issued=None,
                    status="ambiguous",
                    match_candidates=[
                        {"patient_id": str(candidate.id), "reason": "demographic"}
                        for candidate in resolution.candidates
                    ],
                )
                # store_link_token is deliberately not called here: the token
                # exists to complete care-context linking against a *resolved*
                # patient, and until a human picks the right candidate there is
                # nothing to link it to. ``link_token_enc`` stays NULL.

                # The idempotency ledger row above is what makes the replay
                # early-return work for this branch too; returning from inside
                # atomic() commits the queue entry, consent and log together.
                ack = ABHACallbackAckSerializer({
                    "status": "ambiguous",
                    "token": None,
                    "request_id": request_id,
                    "patient_id": str(patient.id),
                    "consent_event": consent_event,
                })
                return Response(ack.data, status=status.HTTP_200_OK)

            if resolution.kind == "matched":
                patient = resolution.patient
                # A demographic match is weak evidence: name, birth year and
                # gender agree, but nobody confirmed them, so the record goes
                # back into the verification queue. A record the front desk
                # already verified is never demoted by a gateway guess —
                # ``pending`` written over ``verified`` would queue a confirmed
                # patient. An exact ABHA match skips this write entirely: it is
                # the strong identifier and changes nothing about the status.
                if (
                    resolution.matched_by == "demographic"
                    and patient.verification_status != "verified"
                ):
                    patient.verification_status = "pending"
                    patient.save(update_fields=["verification_status"])
            else:
                patient = self._create_provisional_patient(profile)

            # ABD-010: issue token
            try:
                token = self._issue_token(department, patient.id)
            except _NoOpdDepartment:
                # No department means no queue to put the patient in. Refusing
                # is better than inventing a department the front desk does not
                # recognise.
                logger.error(
                    "ABDM callback: no OPD-enabled department for tenant %s", tenant_id
                )
                return Response(
                    {"status": "rejected", "detail": "No OPD department is configured"},
                    status=status.HTTP_409_CONFLICT,
                )

            # ABD-011: record the consent event, and ABD-012: store the link
            # token encrypted. Both writes sit inside the request transaction
            # alongside the patient registration and the token, so the consent
            # record and the patient it names cannot come apart: a rollback of
            # one is a rollback of all of them, and a dangling consent row
            # pointing at a patient that no longer exists is worse than no
            # consent row at all.
            consent_event = record_consent_event(
                tenant_id=tenant_id,
                patient_id=patient.id,
                request_id=request_id,
                source_app=payload.get("sourceApp") or "ABDM",
                purpose="registration",
                facility_id=facility_id,
                raw_profile_hash=hash_profile(profile),
            )

            # ABD-012: the link token exists only for care-context linking. It
            # is sealed into the log row and never echoed in the
            # acknowledgement — the gateway does not need the value, and an
            # ack is the one part of this flow that logs and proxies see.
            link_token = secrets.token_urlsafe(32)

            # Log the callback
            log = ABHACallbackLog.objects.create(
                tenant_id=tenant_id,
                request_id=request_id,
                facility_abdm_id=hip_id,
                ip=request.META.get("REMOTE_ADDR"),
                profile=json.dumps(profile)[:4000],  # truncate large payloads
                matched_patient_id=patient.id,
                token_issued=token,
                status="ok",
            )
            store_link_token(log_id=log.id, token=link_token)

        ack = ABHACallbackAckSerializer({
            "status": "ok",
            "token": token,
            "request_id": request_id,
            "patient_id": str(patient.id),
            "consent_event": consent_event,
        })
        return Response(ack.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def health(self, request):
        """Health check for the ABDM gateway adapter."""
        return Response({"status": "ok", "service": "abdm-gateway"})
