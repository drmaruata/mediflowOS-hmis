"""Patient registry views."""
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from common.tenant import TENANT_REQUIRED_MESSAGE, TenantScopedQuerysetMixin
from .models import Patient, IntakePoint, QRCode
from .serializers import PatientSerializer, IntakePointSerializer, QRCodeSerializer
from .services import birth_year, find_duplicates


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
        approximate window.
        """
        predicate = Q()
        for year in years:
            predicate |= (
                Q(demographics__yearOfBirth=year)
                | Q(demographics__year_of_birth=year)
                | Q(demographics__dob__startswith=f"{year}-")
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
            queryset = queryset.filter(
                Q(uhid__icontains=term)
                | Q(abha_number__icontains=term)
                | Q(abha_address__icontains=term)
                | Q(demographics__name__icontains=term)
                | Q(contact__mobile__icontains=term)
            )

        name = (request.query_params.get("name") or "").strip()
        if name:
            queryset = queryset.filter(demographics__name__icontains=name)
        mobile = (request.query_params.get("mobile") or "").strip()
        if mobile:
            queryset = queryset.filter(contact__mobile__icontains=mobile)
        abha = (request.query_params.get("abha_number") or "").strip()
        if abha:
            queryset = queryset.filter(abha_number__icontains=abha)

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


class IntakePointViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = IntakePointSerializer
    queryset = IntakePoint.objects.all()


class QRCodeViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Facility and counter QR codes for ABDM Scan and Share.

    ``encode_data`` carries the facility's HIP ID, which is tenant-identifying,
    so this resource is tenant-scoped like any other patient-registry row.
    """

    serializer_class = QRCodeSerializer
    queryset = QRCode.objects.all()

    def perform_create(self, serializer):
        from rest_framework.exceptions import PermissionDenied, ValidationError

        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        
        facility = serializer.validated_data.get("facility")
        if not facility or not facility.abdm_hip_id:
            raise ValidationError({"facility": "Facility must have an ABDM HIP ID to generate a QR code."})
            
        intake_point = serializer.validated_data.get("intake_point")
        counter_code = intake_point.counter_id if intake_point and intake_point.counter_id else ""
        
        # Format: HIP_ID + optional counter code. This is what the ABDM scanning app reads
        # and sends back in the callback payload.
        encode_data = f"{facility.abdm_hip_id}-{counter_code}" if counter_code else facility.abdm_hip_id
        
        serializer.save(
            tenant_id=tenant_id,
            encode_data=encode_data
        )

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        qr = self.get_object()
        qr.regenerated_at = timezone.now()
        qr.save(update_fields=["regenerated_at"])
        return Response({"status": "regenerated"})
