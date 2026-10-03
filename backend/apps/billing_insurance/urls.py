"""Billing URLs."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "billing"

router = DefaultRouter()
router.register(r"tariffs", views.TariffViewSet, basename="tariff")
router.register(r"invoices", views.InvoiceViewSet, basename="invoice")
router.register(r"payments", views.PaymentViewSet, basename="payment")
router.register(r"claims", views.ClaimViewSet, basename="claim")

urlpatterns = [
    *router.urls,
    path("invoices/<uuid:pk>/pay/", views.InvoiceViewSet.as_view({"post": "pay"}), name="invoice-pay"),
]
