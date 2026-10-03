"""Billing views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import Claim, Invoice, Payment, Tariff
from .serializers import ClaimSerializer, InvoiceSerializer, PaymentSerializer, TariffSerializer


class TariffViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = TariffSerializer
    queryset = Tariff.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})


class InvoiceViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    queryset = Invoice.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Record a payment against an invoice."""
        invoice = self.get_object()
        amount = request.data.get("amount", invoice.total)
        payment = Payment.objects.create(
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            amount=amount,
            method=request.data.get("method", "cash"),
            receipt_no=request.data.get("receipt_no"),
        )
        invoice.status = "paid"
        invoice.save(update_fields=["status"])
        return Response({"invoice": InvoiceSerializer(invoice).data, "payment": PaymentSerializer(payment).data}, status=status.HTTP_201_CREATED)


class PaymentViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = PaymentSerializer
    queryset = Payment.objects.all()


class ClaimViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = ClaimSerializer
    queryset = Claim.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})
