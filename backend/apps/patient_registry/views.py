"""Patient registry views."""
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from common.tenant import TENANT_REQUIRED_MESSAGE, TenantScopedQuerysetMixin
from .models import Patient, IntakePoint, QRCode
from .serializers import PatientSerializer, IntakePointSerializer, QRCodeSerializer


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

    @action(detail=False, methods=["get"])
    def search(self, request):
        """UHID / ABHA lookup for the registration counter (P-REG-1).

        One queryset with OR-ed predicates. The previous version combined two
        separately-filtered querysets with ``|``, which reintroduced the
        unfiltered base queryset and silently dropped the tenant scope.

        The tenant comes from ``TenantScopedQuerysetMixin``, so a request with
        no resolved tenant searches nothing rather than every tenant.
        """
        term = (request.query_params.get("q") or "").strip()
        queryset = self.get_queryset()
        if term:
            queryset = queryset.filter(
                Q(uhid__icontains=term) | Q(abha_number__icontains=term)
            )
        return Response(PatientSerializer(queryset[:20], many=True).data)

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
