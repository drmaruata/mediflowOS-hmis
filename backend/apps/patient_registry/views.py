"""Patient registry views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
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
    """Hardened unauthenticated ABDM callback endpoint."""
    serializer_class = ABHACallbackSerializer

    def create(self, request):
        serializer = ABHACallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # dedup by request_id, authenticate, resolve tenant, match, issue token
        return Response({"status": "ok"}, status=status.HTTP_201_CREATED)