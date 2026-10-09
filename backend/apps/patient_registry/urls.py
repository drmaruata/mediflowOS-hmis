from django.urls import path
from rest_framework.routers import DefaultRouter
from . import views

app_name = "patient"

router = DefaultRouter()
router.register(r"patients", views.PatientViewSet, basename="patient")
router.register(r"intake-points", views.IntakePointViewSet, basename="intakepoint")
router.register(r"qr-codes", views.QRCodeViewSet, basename="qrcode")

urlpatterns = [
    # OP slip print contract (REG-011): keyed by the OPD encounter id, which
    # the product calls the "visit". Owned by patient_registry per the R1 plan
    # (the slip is a registry-facing document) rather than the opd router; the
    # ``<uuid:>`` converter answers 404 for a malformed id, the same fail-closed
    # shape an unknown or foreign visit gets.
    path(
        "visits/<uuid:visit_id>/op-slip/",
        views.OpSlipView.as_view(),
        name="visit-op-slip",
    ),
    *router.urls,
]
