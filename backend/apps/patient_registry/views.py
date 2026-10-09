"""Patient registry views."""
import logging

import httpx
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.abdm_gateway.client import (
    ABDMClient,
    ABDMRequestError,
    resolve_sandbox_base_url,
)
from common.crypto import search_index
from common.tenant import TENANT_REQUIRED_MESSAGE, TenantScopedQuerysetMixin
from .models import Patient, IntakePoint, QRCode, field_keys
from .serializers import (
    IntakePointSerializer,
    OpSlipSerializer,
    PatientSerializer,
    QRCodeSerializer,
)
from .services import birth_year, find_duplicates
from .validation import normalise_mobile

logger = logging.getLogger(__name__)


class AbdmErrorResponseSerializer(serializers.Serializer):
    """Structured error body the ABDM ABHA actions answer (REG-009).

    Every failure shape — 400 validation misses, the 502 sandbox-unreachable
    path and both 503s — is ``{status, code, detail}``, and the whole point of
    the shape is that it is stable, so one shared component is used for all of
    them in the schema. The ``code`` values are the stable machine keys
    (``ABDM_SANDBOX_UNCONFIGURED``, ``ABHA_NOT_LINKED``, ...).
    """

    status = serializers.CharField()
    code = serializers.CharField()
    detail = serializers.CharField()


class PatientViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = PatientSerializer
    queryset = Patient.objects.all()

    def _resolve_intake_department(self, department_id, tenant_id):
        """Resolve a registration's intake department within the tenant.

        A department the caller names must belong to this tenant, or the
        registration would mint a token into another hospital's queue. None
        means "no intake department" — the registration lands without a token.
        """
        if department_id is None:
            return None
        from apps.identity_tenancy.models import Department

        department = Department.objects.filter(
            tenant_id=tenant_id, id=department_id
        ).first()
        if department is None:
            raise ValidationError(
                {"intake_department_id": "Unknown department for this tenant."}
            )
        return department

    def _issue_intake_token(self, patient, department, tenant_id):
        """Mint the OPD token the registration response carries (REG-010)."""
        from apps.opd.models import Token
        from apps.opd.services import next_token_number

        prefix, number = next_token_number(
            tenant_id=tenant_id,
            facility_id=department.facility_id,
            department_id=department.id,
        )
        Token.objects.create(
            tenant_id=tenant_id,
            patient_id=patient.id,
            department_id=department.id,
            series=prefix,
            number=number,
            status="waiting",
        )
        return {"series": prefix, "number": number}

    def perform_create(self, serializer):
        """Assign the server-generated UHID, then mint the intake token.

        ``TenantScopedQuerysetMixin.perform_create`` stamps the tenant and
        writes the audit row, but it cannot be reused as-is: the UHID must be
        decided *before* the patient row exists (it is a NOT NULL column), so
        the tenant guard is replicated here and the mixin's audit helper is
        invoked explicitly afterwards.
        """
        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied(TENANT_REQUIRED_MESSAGE)

        from apps.patient_registry.services import generate_uhid

        department = self._resolve_intake_department(
            serializer.validated_data.pop("intake_department_id", None), tenant_id
        )
        uhid = generate_uhid(tenant_id=tenant_id)
        serializer.save(tenant_id=tenant_id, uhid=uhid)
        self._write_audit_log(serializer.instance, "create")

        self._registration_token = (
            self._issue_intake_token(serializer.instance, department, tenant_id)
            if department is not None
            else None
        )

    def create(self, request, *args, **kwargs):
        """Create a patient, appending the issued OPD token when present (REG-010).

        ``token`` is a response-level field: it is data about the intake, not
        about the patient, so it belongs next to the representation rather
        than inside it.
        """
        # Viewset instances may be reused by DRF; a token left over from a
        # previous call must never leak into the next response.
        self._registration_token = None
        response = super().create(request, *args, **kwargs)
        if self._registration_token is not None:
            response.data["token"] = self._registration_token
        return response

    @staticmethod
    def _int_query(request, name):
        """Parse an integer query parameter, refusing junk explicitly.

        Silently ignoring a malformed ``age=`` would make the filter look like
        it applied when it did not.
        """
        raw = request.query_params.get(name)
        if raw in (None, ""):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ValidationError({name: "Must be an integer."})

    @staticmethod
    def _birth_year_q(years):
        """A portable OR over the birth keys for the given calendar years.

        ``demographics`` key transforms compile to ``json_extract`` on SQLite
        and ``->>`` on PostgreSQL, so the same filter runs on both. ``dob`` is
        matched by its leading year because its day/month are irrelevant to an
        approximate window; a bare-year ``dob`` (``"1980"``) is matched exactly
        because :func:`~apps.patient_registry.services.birth_year` also accepts
        that form for duplicate-check. ``age_years`` is converted at query time
        (``current year - stored age``) so a patient whose only birth key was
        the REG-007 ``age_years`` shape is found without rewriting stored rows.
        """
        current_year = timezone.now().year
        predicate = Q()
        for year in years:
            predicate |= (
                Q(demographics__yearOfBirth=year)
                | Q(demographics__year_of_birth=year)
                | Q(demographics__dob__startswith=f"{year}-")
                | Q(demographics__dob=str(year))
                | Q(demographics__age_years=current_year - year)
            )
        return predicate

    @action(detail=False, methods=["get"])
    def search(self, request):
        """UHID / name / mobile / ABHA / age lookup for the counter (REG-002).

        One queryset with OR-ed predicates. The previous version combined two
        separately-filtered querysets with ``|``, which reintroduced the
        unfiltered base queryset and silently dropped the tenant scope.

        The tenant comes from ``TenantScopedQuerysetMixin``, so a request with
        no resolved tenant searches nothing rather than every tenant.
        """
        queryset = self.get_queryset()

        term = (request.query_params.get("q") or "").strip()
        if term:
            # REG-008: identifiers are ciphertext, so containment probes are
            # impossible; the HMAC ``*_idx`` columns only answer exact values.
            # A `q` hits a row whose *whole* uhid/name matches the old way,
            # whose ABHA number/address equals ``term`` exactly, or whose mobile
            # normalises to ``term`` (so a formatted ``+91`` probe still meets
            # the bare national number — pinned by
            # tests/integration/test_patient_encryption.py). A fragment such as
            # ``9876`` deliberately matches nothing, which is the documented
            # degradation of exact-digest search.
            _, hmac_key = field_keys()
            term_q = (
                Q(uhid__icontains=term) | Q(demographics__name__icontains=term)
            )
            term_q |= Q(abha_number_idx=search_index(term, key=hmac_key))
            term_q |= Q(abha_address_idx=search_index(term, key=hmac_key))
            canonical_mobile = normalise_mobile(term)
            if canonical_mobile:
                term_q |= Q(mobile_idx=search_index(canonical_mobile, key=hmac_key))
            queryset = queryset.filter(term_q)

        name = (request.query_params.get("name") or "").strip()
        if name:
            queryset = queryset.filter(demographics__name__icontains=name)
        mobile = (request.query_params.get("mobile") or "").strip()
        if mobile:
            # The probe is canonicalised exactly like the write path, so a
            # formatted ``+91``/spaced parameter meets the bare national number
            # stored in the index.
            _, hmac_key = field_keys()
            queryset = queryset.filter(
                mobile_idx=search_index(normalise_mobile(mobile), key=hmac_key)
            )
        abha = (request.query_params.get("abha_number") or "").strip()
        if abha:
            _, hmac_key = field_keys()
            queryset = queryset.filter(
                abha_number_idx=search_index(abha, key=hmac_key)
            )

        year = self._int_query(request, "year_of_birth")
        if year is not None:
            queryset = queryset.filter(self._birth_year_q([year]))

        age = self._int_query(request, "age")
        if age is not None:
            # Approximate by design: a person "aged 45" this year was born
            # either this year minus 45 or the year before, so a +/-1 year
            # window is what finds the 44-46 cohort REG-002 describes.
            target = timezone.now().year - age
            queryset = queryset.filter(
                self._birth_year_q([target - 1, target, target + 1])
            )

        return Response(PatientSerializer(queryset[:20], many=True).data)

    @staticmethod
    def _duplicate_candidate(patient):
        """The minimum a clerk needs to recognise a match — no full PHI.

        A UHID, name, gender, birth year and the last four mobile digits are
        enough to say "that is them"; the full ABHA and mobile are deliberately
        withheld so a probe cannot be used to harvest identifiers.
        """
        demographics = patient.demographics or {}
        mobile = str((patient.contact or {}).get("mobile") or "")
        return {
            "id": str(patient.id),
            "uhid": patient.uhid,
            "name": demographics.get("name"),
            "gender": demographics.get("gender"),
            "year_of_birth": birth_year(demographics),
            "mobile_masked": "*" * max(len(mobile) - 4, 0) + mobile[-4:],
        }

    @extend_schema(
        request=inline_serializer(
            name="DuplicateCheckRequest",
            fields={
                "name": serializers.CharField(required=False, allow_blank=True),
                "dob": serializers.CharField(required=False, allow_blank=True),
                "mobile": serializers.CharField(required=False, allow_blank=True),
                "abha_number": serializers.CharField(required=False, allow_blank=True),
            },
        ),
        responses={
            200: inline_serializer(
                name="DuplicateCheckResponse",
                fields={
                    "warn": serializers.BooleanField(),
                    "candidates": serializers.ListField(
                        child=serializers.DictField()
                    ),
                },
            )
        },
    )
    @action(detail=False, methods=["post"], url_path="duplicate-check")
    def duplicate_check(self, request):
        """Warn about probable duplicates before a registration is saved (REG-003).

        The probe is tenant-scoped like every other patient query, and returns
        only enough to recognise a match. Nothing here is logged: a duplicate
        probe carries a name and an identifier, which are PHI.
        """
        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied(TENANT_REQUIRED_MESSAGE)

        data = request.data if isinstance(request.data, dict) else {}
        candidates = find_duplicates(
            tenant_id=tenant_id,
            candidate={
                "name": data.get("name"),
                "dob": data.get("dob"),
                "mobile": data.get("mobile"),
                "abha_number": data.get("abha_number"),
            },
        )
        return Response(
            {
                "warn": bool(candidates),
                "candidates": [self._duplicate_candidate(p) for p in candidates],
            }
        )

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        """Move a patient from verification queue to verified (P-REG-6)."""
        patient = self.get_object()
        if patient.verification_status != "pending":
            return Response(
                {"detail": "Patient is not pending verification."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        patient.verification_status = "verified"
        patient.verified_at = timezone.now()
        patient.save(update_fields=["verification_status", "verified_at"])
        return Response(PatientSerializer(patient).data)

    @action(detail=False, methods=["get"])
    def verification_queue(self, request):
        """List patients pending identity verification (P-REG-6)."""
        queryset = self.get_queryset().filter(verification_status="pending")
        return Response(PatientSerializer(queryset, many=True).data)

    # --- ABDM outbound ABHA actions (REG-009) ---------------------------

    @staticmethod
    def _abdm_request_body(request):
        """The parsed request body, or None when it is not a JSON object.

        A JSON array (or any non-object) body is not a payload the adapter
        can forward: silently coercing it to ``{}`` would both send a create
        the client never wrote and mislabel the failure as the sandbox's, so
        the actions answer the precise ``ABDM_REQUEST_INVALID`` 400 instead
        of forwarding.
        """
        data = request.data
        return data if isinstance(data, dict) else None

    def _abdm_invalid_body_response(self):
        """The stable 400 a non-object ABHA request body answers (REG-009)."""
        return Response(
            {
                "status": "error",
                "code": "ABDM_REQUEST_INVALID",
                "detail": "Request body must be a JSON object.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _abdm_dispatch(self, method, *args):
        """Run an ABDMClient method, or answer the structured 503.

        With no sandbox configured the action must fail closed: there is no
        request the adapter could make, so a fabricated 200 would be a lie
        (REG-009). A non-2xx sandbox response is mirrored with its status; a
        failure before any response answers 502.
        """
        tenant_id = self.get_tenant_id()
        try:
            base_url = resolve_sandbox_base_url(tenant_id)
        except ImproperlyConfigured as exc:
            return Response(
                {
                    "status": "unavailable",
                    "code": "ABDM_SANDBOX_MISCONFIGURED",
                    "detail": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not base_url:
            return Response(
                {
                    "status": "unavailable",
                    "code": "ABDM_SANDBOX_UNCONFIGURED",
                    "detail": (
                        "The ABDM sandbox is not configured: set "
                        "ABDM_SANDBX_BASE_URL or the tenant's ABDM "
                        "IntegrationAdapter config.base_url."
                    ),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            result = getattr(ABDMClient(base_url), method)(*args)
        except ABDMRequestError as exc:
            mirror = (
                exc.status_code
                if exc.status_code is not None and 400 <= exc.status_code < 600
                else status.HTTP_502_BAD_GATEWAY
            )
            return Response(
                {"status": "error", "code": "ABDM_REQUEST_FAILED", "detail": str(exc)},
                status=mirror,
            )
        except httpx.TransportError:
            logger.warning(
                "ABDM sandbox unreachable for tenant %s (%s)", tenant_id, method
            )
            return Response(
                {
                    "status": "error",
                    "code": "ABDM_SANDBOX_UNREACHABLE",
                    "detail": "The ABDM sandbox could not be reached.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(result)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description=(
                    "The sandbox's create response, passed through verbatim. "
                    "The create spec is unresolved (REG-009) so the exact "
                    "shape is not pinned."
                ),
            ),
            400: AbdmErrorResponseSerializer,
            502: AbdmErrorResponseSerializer,
            503: AbdmErrorResponseSerializer,
        },
        description=(
            "Create a new ABHA for this patient through the ABDM sandbox "
            "(REG-009). The request body is passed through to the sandbox "
            "enrollment API verbatim; the sandbox create spec is unresolved, "
            "so the schema is deliberately not pinned. Answers 400 with code "
            "`ABDM_REQUEST_INVALID` when the body is not a JSON object, 503 "
            "with code `ABDM_SANDBOX_UNCONFIGURED` when the sandbox is not "
            "configured, and 502 with code `ABDM_SANDBOX_UNREACHABLE` when it "
            "cannot be reached or `ABDM_REQUEST_FAILED` when the sandbox "
            "answers non-2xx or a 2xx that is not JSON - never a fabricated "
            "success. Tenant-scoped: a patient of another tenant answers 404."
        ),
    )
    @action(detail=True, methods=["post"], url_path="abha/create")
    def abha_create(self, request, pk=None):
        """Create a new ABHA at the counter (REG-009)."""
        self.get_object()
        payload = self._abdm_request_body(request)
        if payload is None:
            return self._abdm_invalid_body_response()
        return self._abdm_dispatch("create_abha", payload)

    @extend_schema(
        request=inline_serializer(
            name="AbhaVerifyRequest",
            fields={"otp": serializers.CharField(allow_blank=True)},
        ),
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description=(
                    "The sandbox's verify response, passed through verbatim. "
                    "The verify spec is unresolved (REG-009) so the exact "
                    "shape is not pinned."
                ),
            ),
            400: AbdmErrorResponseSerializer,
            502: AbdmErrorResponseSerializer,
            503: AbdmErrorResponseSerializer,
        },
        description=(
            "Verify this patient's existing ABHA with the mobile OTP they "
            "received (REG-009). Answers 400 when the patient has no ABHA, "
            "no OTP was sent, or the body is not a JSON object; 503 with "
            "code `ABDM_SANDBOX_UNCONFIGURED` when the sandbox is not "
            "configured; and 502 with code `ABDM_SANDBOX_UNREACHABLE` when it "
            "cannot be reached or `ABDM_REQUEST_FAILED` when the sandbox "
            "answers non-2xx or a 2xx that is not JSON. Tenant-scoped: a "
            "patient of another tenant answers 404."
        ),
    )
    @action(detail=True, methods=["post"], url_path="abha/verify")
    def abha_verify(self, request, pk=None):
        """Verify an existing ABHA at the counter (REG-009)."""
        patient = self.get_object()
        data = self._abdm_request_body(request)
        if data is None:
            return self._abdm_invalid_body_response()
        if not patient.abha_number:
            return Response(
                {
                    "status": "error",
                    "code": "ABHA_NOT_LINKED",
                    "detail": "This patient has no ABHA number to verify.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        otp = str(data.get("otp") or "")
        if not otp:
            return Response(
                {
                    "status": "error",
                    "code": "OTP_REQUIRED",
                    "detail": "An OTP is required to verify the ABHA.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._abdm_dispatch("verify_abha", patient.abha_number, otp)


class IntakePointViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = IntakePointSerializer
    queryset = IntakePoint.objects.all()


class QRCodeViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Facility, counter and department QR codes for ABDM Scan and Share.

    ``encode_data`` carries the facility's HIP ID, which is tenant-identifying,
    so this resource is tenant-scoped like any other patient-registry row.
    """

    serializer_class = QRCodeSerializer
    queryset = QRCode.objects.all()

    @staticmethod
    def _encode_data(facility, intake_point, department):
        """The ABDM Scan-and-Share string: ``HIP[-counter][-department_id]``.

        This is what the scanning app reads and sends back in the callback
        payload. The department segment is the row's own UUID: Department has
        no machine code column yet, so the id is the stable token the callback
        resolves by — the same lookahead ``opd/services.py`` uses for a future
        additive code column.
        """
        parts = [facility.abdm_hip_id]
        if intake_point is not None and intake_point.counter_id:
            parts.append(intake_point.counter_id)
        if department is not None:
            parts.append(str(department.id))
        return "-".join(parts)

    def perform_create(self, serializer):
        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")

        facility = serializer.validated_data.get("facility")
        if not facility or not facility.abdm_hip_id:
            raise ValidationError(
                {"facility": "Facility must have an ABDM HIP ID to generate a QR code."}
            )

        # ``department`` is a validated in-tenant Department instance (see
        # validate_department in the serializer); encoding it here routes the
        # scan to that department when the ABDM flow permits (REG-013).
        serializer.save(
            tenant_id=tenant_id,
            encode_data=self._encode_data(
                facility,
                serializer.validated_data.get("intake_point"),
                serializer.validated_data.get("department"),
            ),
        )

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        """Rebuild ``encode_data`` from the row's own relationships (REG-013).

        A regenerate re-derives the encoding from the *stored* facility, intake
        point and department so the QR matches the department it now points at,
        stamps ``regenerated_at``, and records the change in the audit trail
        (AUD-001): an encode_data change is a queue-routing change and has to
        be traceable. The audit row is written directly to ``audit.event`` with
        the ``source`` marker because the mixin's write path cannot express a
        machine-initiated event.
        """
        qr = self.get_object()
        qr.encode_data = self._encode_data(qr.facility, qr.intake_point, qr.department)
        qr.regenerated_at = timezone.now()
        qr.save(update_fields=["encode_data", "regenerated_at"])

        from apps.audit.models import AuditEvent

        AuditEvent.objects.create(
            tenant_id=self.get_tenant_id(),
            user_id=(
                request.user.pk if request.user.is_authenticated else None
            ),
            action="update",
            entity_type="qr_code",
            entity_id=str(qr.id),
            source="qr.regenerate",
        )
        return Response(QRCodeSerializer(qr).data)


class OpSlipView(APIView):
    """OP slip print payload for an OPD encounter (REG-011, REG-012).

    ``visit_id`` is the OPD encounter's primary key — the product calls the
    encounter a "visit", and there is no separate visit-table row. Every
    lookup is tenant-scoped because the payload carries PHI (the patient's
    UHID and name): a visit that does not exist in this tenant answers 404
    exactly like an unknown id, so the endpoint cannot be used to probe for
    another hospital's encounters.
    """

    @extend_schema(
        responses={200: OpSlipSerializer},
        description=(
            "The JSON print contract for an OP slip (REG-011, REG-012): "
            "denormalised patient, token, department and facility values. "
            "``token``/``issued_at`` are null when the visit has no issued "
            "token."
        ),
    )
    def get(self, request, visit_id):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            # Mirror TenantScopedQuerysetMixin: an unresolved tenant resolves
            # to an empty queryset, so its detail lookups answer 404. Same
            # fail-closed shape here, so a membership-less token probes nothing.
            raise NotFound()

        from apps.identity_tenancy.models import Department, Facility
        from apps.opd.models import OPDEncounter, Token

        encounter = get_object_or_404(
            OPDEncounter.objects.filter(tenant_id=tenant_id), pk=visit_id
        )
        patient = get_object_or_404(
            Patient.objects.filter(tenant_id=tenant_id), pk=encounter.patient_id
        )
        department = get_object_or_404(
            Department.objects.filter(tenant_id=tenant_id),
            pk=encounter.department_id,
        )
        # The encounter and token carry no facility id; the department is the
        # row that names its facility (Department.facility is a required FK,
        # so the slip resolves through it rather than duplicating the id).
        facility = get_object_or_404(
            Facility.objects.filter(tenant_id=tenant_id),
            pk=department.facility_id,
        )

        # There is no FK joining Token to the encounter, so the slip's token is
        # keyed by the same (tenant, patient, department) triple the encounter
        # carries. ``-issued_at`` picks the latest row: a re-issued token is
        # the one the queue is now showing for this patient, not the first one
        # minted for the visit.
        token = (
            Token.objects.filter(
                tenant_id=tenant_id,
                patient_id=encounter.patient_id,
                department_id=encounter.department_id,
            )
            .order_by("-issued_at")
            .first()
        )

        demographics = patient.demographics or {}
        payload = {
            "uhid": patient.uhid,
            # REG-007 requires a name at registration; the blank fallback only
            # ever renders a legacy/corrupt row instead of 500ing the print
            # endpoint, and a blank name on the slip is visibly wrong.
            "patient_name": str(demographics.get("name") or ""),
            "token": (
                {"series": token.series, "number": token.number}
                if token is not None
                else None
            ),
            "department": department.name,
            "facility": facility.name,
            "issued_at": token.issued_at if token is not None else None,
            "visit_date": encounter.registration_time.date(),
        }
        return Response(OpSlipSerializer(payload).data)
