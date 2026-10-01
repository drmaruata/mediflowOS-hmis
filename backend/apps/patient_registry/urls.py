from rest_framework.routers import DefaultRouter
from . import views

app_name = "patient"

router = DefaultRouter()
router.register(r"patients", views.PatientViewSet, basename="patient")
router.register(r"intake-points", views.IntakePointViewSet, basename="intakepoint")
router.register(r"qr-codes", views.QRCodeViewSet, basename="qrcode")
router.register(r"abdm-callbacks", views.ABHACallbackViewSet, basename="abdmcallback")

urlpatterns = router.urls
