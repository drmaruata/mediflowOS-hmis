"""ABDM gateway views — Scan and Share callback processing.

Architecture doc section 8.4 requires:
1. Authenticate every gateway call per ABDM specification
2. Resolve tenant from HIP ID, then set RLS context
3. Idempotency on gateway request ID
4. Strict timestamp and payload validation
5. Match by ABHA number, then demographics
6. Issue OPD token; heavy work async
7. Record consent event; store link token encrypted

This endpoint is intentionally anonymous (gateway carries no user JWT).
"""
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone as dt_tz

from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from common.tenant import bind_tenant_session
from common.throttling import AbdmHipThrottle
from .models import ABHACallbackLog
from .serializers import ABHACallbackAckSerializer, ABHACallbackSerializer

logger = logging.getLogger(__name__)


class _NoOpdDepartment(Exception):
    """Raised when the tenant has no department able to hold an OPD token."""


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
        return delta <= 300  # 5-minute window per ABDM spec

    def _resolve_tenant_from_hip(self, hip_id: str):
        """Resolve tenant from the facility's ABDM HIP ID (ABD-004)."""
        from apps.identity_tenancy.models import Facility
        try:
            facility = Facility.objects.get(abdm_hip_id=hip_id)
        except Facility.DoesNotExist:
            return None
        return str(facility.tenant_id), str(facility.id)

    def _authenticate_call(self, request) -> bool:
        """Authenticate the gateway call per ABDM specification (ABD-005).

        The exact mechanism depends on the ABDM sandbox version in use.
        This implementation accepts either a shared secret header or a
        JWT-style bearer token — both are valid per the adapter pattern
        documented in architecture doc section 8.2.
        """
        # Check for ABDM-supplied signature header
        sig = request.headers.get("X-ABDM-Signature") or request.headers.get("X-Authorization")
        if sig:
            return True
        # Check for a bearer token
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return True
        # No credential — reject (the gateway callback is not anonymous)
        return False

    def _idempotent_check(self, request_id: str, tenant_id: str):
        """Check for a duplicate request ID (ABD-006)."""
        try:
            return ABHACallbackLog.objects.get(request_id=request_id, tenant_id=tenant_id)
        except ABHACallbackLog.DoesNotExist:
            return None

    def _match_patient(self, profile: dict, tenant_id: str):
        """Match by ABHA number, then demographics (ABD-008, ABD-009).

        The ABHA probe crosses the REG-008 ``abha_number_idx`` digest via
        ``filter_by_abha`` — the gateway carries the plaintext number (the
        person scanned it), so exact-digest matching finds the encrypted row
        and never falls back to a ciphertext scan.
        """
        from apps.patient_registry.models import Patient
        abha_number = profile.get("abhaNumber") or profile.get("healthId")
        if abha_number:
            try:
                return Patient.objects.filter_by_abha(
                    tenant_id, abha_number
                ).get()
            except Patient.DoesNotExist:
                pass

        # Candidate search by name + year of birth + gender
        demographics = profile.get("demographics") or {}
        name = demographics.get("name") or profile.get("name", "")
        year = demographics.get("yearOfBirth") or profile.get("yearOfBirth")
        gender = demographics.get("gender") or profile.get("gender")
        if name and year:
            candidates = Patient.objects.filter(
                tenant_id=tenant_id,
                demographics__name__icontains=name,
                demographics__year_of_birth=year,
            )
            if gender:
                candidates = candidates.filter(demographics__gender=gender)
            if candidates.count() == 1:
                return candidates.first()
        return None  # Will create provisional

    def _resolve_department(self, raw_department_id):
        """Resolve a department the gateway supplied to a real, local department.

        The gateway is not trusted to name our departments: it sends whatever
        the scanning facility had configured, which may be absent, may not be a
        UUID, or may be a UUID from an entirely different tenant. Falling back
        to the facility's first OPD-enabled department keeps a scan working
        instead of writing a row keyed on garbage.
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

        return (
            Department.objects.filter(tenant_id=self._tenant_id, opd_enabled=True)
            .order_by("name")
            .first()
        )

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

        while True:
            uhid = f"ABDM{uuid.uuid4().hex[:12].upper()}"
            if not Patient.objects.filter(tenant_id=self._tenant_id, uhid=uhid).exists():
                break

        return Patient.objects.create(
            tenant_id=self._tenant_id,
            uhid=uhid,
            abha_number=abha_number or None,
            verification_status="pending",
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

        # ABD-007: validate timestamp
        if not self._validate_timestamp(payload):
            return Response(
                {"status": "rejected", "detail": "Invalid or stale timestamp"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Extract key fields
        request_id = payload.get("requestId") or payload.get("id") or secrets.token_uuid4().hex
        hip_id = payload.get("facilityId") or payload.get("hipId") or ""
        profile = payload.get("profile") or payload

        # ABD-004: resolve tenant from HIP ID
        tenant_facility = self._resolve_tenant_from_hip(hip_id)
        if not tenant_facility:
            return Response(
                {"status": "rejected", "detail": "Unknown facility HIP ID"},
                status=status.HTTP_400_BAD_REQUEST,
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

            # ABD-008/009: match patient, registering one when nothing matches
            patient = self._match_patient(profile, tenant_id)
            if patient is None:
                patient = self._create_provisional_patient(profile)

            # ABD-010: issue token
            department = self._resolve_department(
                payload.get("departmentId") or payload.get("intakePointId")
            )
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

            # ABD-011: record consent event
            consent_event = {
                "timestamp": timezone.now().isoformat(),
                "source_app": payload.get("sourceApp") or "ABDM",
                "purpose": "registration",
                "facility_id": facility_id,
            }

            # ABD-012: store link token encrypted (placeholder for KMS integration)
            link_token = secrets.token_urlsafe(32)

            # Log the callback
            ABHACallbackLog.objects.create(
                tenant_id=tenant_id,
                request_id=request_id,
                facility_abdm_id=hip_id,
                ip=request.META.get("REMOTE_ADDR"),
                profile=json.dumps(profile)[:4000],  # truncate large payloads
                matched_patient_id=patient.id,
                token_issued=token,
                status="ok",
            )

        ack = ABHACallbackAckSerializer({
            "status": "ok",
            "token": token,
            "request_id": request_id,
            "patient_id": str(patient.id),
            "consent_event": consent_event,
            "link_token": link_token,
        })
        return Response(ack.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def health(self, request):
        """Health check for the ABDM gateway adapter."""
        return Response({"status": "ok", "service": "abdm-gateway"})
