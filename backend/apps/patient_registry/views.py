"""Patient registry views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.utils import timezone
from common.throttling import AbdmHipThrottle
from .models import Patient, IntakePoint, QRCode
from .serializers import PatientSerializer, IntakePointSerializer, QRCodeSerializer, ABHACallbackSerializer


class PatientViewSet(viewsets.ModelViewSet):
    serializer_class = PatientSerializer
    queryset = Patient.objects.all()

    @action(detail=False, methods=["get"])
    def search(self, request):
        q = request.query_params.get("q", "")
        qs = self.queryset.filter(tenant_id=request.headers.get("X-Tenant-Id"))
        if q:
            qs = qs.filter(uhid__icontains=q) | self.queryset.filter(
                tenant_id=request.headers.get("X-Tenant-Id"), abha_number__icontains=q
            )
        return Response(PatientSerializer(qs[:20], many=True).data)


class IntakePointViewSet(viewsets.ModelViewSet):
    serializer_class = IntakePointSerializer
    queryset = IntakePoint.objects.all()


class QRCodeViewSet(viewsets.ModelViewSet):
    serializer_class = QRCodeSerializer
    queryset = QRCode.objects.all()

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        qr = self.get_object()
        qr.regenerated_at = timezone.now()
        qr.save()
        return Response({"status": "regenerated"})


class ABHACallbackViewSet(viewsets.ViewSet):
    """ABDM profile-share callback endpoint.

    .. warning::

       **Not implemented. This endpoint always answers 501.**

       An earlier version of this view was documented as "hardened" while
       returning ``{"status": "ok"}`` without authenticating the caller,
       resolving a tenant, deduplicating, or writing anything. That created a
       false impression that Scan and Share was ready. It is not.

       Profile share is a mandatory ABDM certification test case
       (architecture doc section 8), so this endpoint must not pretend
       otherwise until it satisfies every item below. The rate limiting
       requirement (section 8.4) is already implemented via
       :class:`common.throttling.AbdmHipThrottle`; the rest are outstanding.

       Outstanding before this may return anything other than 501
       (architecture doc section 8.4):

       1. Authenticate every gateway call per ABDM's specification before
          touching data. The applicable spec version must be confirmed
          against ABDM sandbox documentation at build time; the doc records
          that v1.0 and v3 paths have coexisted (section 8.2).
       2. Resolve the tenant from the HIP ID, then set the RLS context. There
          is no user JWT on a gateway callback.
       3. Idempotency on the gateway request ID, so retries never create
          duplicate patients or tokens.
       4. Strict timestamp and payload validation; the ABDM forum notes that
          malformed timestamps cause silent acknowledgement failures.
       5. Match by ABHA number, then by demographics, proposing a match or
          queueing for verification; otherwise create a provisional record.
       6. Issue the OPD token, hand off heavy work asynchronously, and
          acknowledge within the gateway's expected response time.
       7. Record the share as a consent event with timestamp, source app and
          purpose (DPDP Act), and store the link token encrypted.

       This endpoint is intentionally anonymous, because a gateway carries no
       user credentials. That is the only reason it opts out of the
       deny-by-default permissions; it must stay non-functional until the
       authentication above exists.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [AbdmHipThrottle]

    # The route stays registered so the ABDM side can be developed against a
    # real endpoint, and so schema generation documents it.
    serializer_class = ABHACallbackSerializer

    def create(self, request):
        return Response(
            {
                "status": "not_implemented",
                "detail": (
                    "ABDM profile-share callback processing is not implemented. "
                    "See the ABHACallbackViewSet docstring for the outstanding "
                    "requirements from the architecture document, section 8.4."
                ),
                "reference": "SaaS HMIS Architecture v0.6.md#section-8.4",
            },
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )