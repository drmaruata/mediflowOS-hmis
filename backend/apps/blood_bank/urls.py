"""Blood Bank URLs."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "blood_bank"

router = DefaultRouter()
router.register(r"donors", views.DonorViewSet, basename="donor")
router.register(r"donations", views.DonationViewSet, basename="donation")
router.register(r"components", views.BloodComponentViewSet, basename="component")
router.register(r"requisitions", views.RequisitionViewSet, basename="requisition")
router.register(r"cross-matches", views.CrossMatchViewSet, basename="crossmatch")
router.register(r"reactions", views.TransfusionReactionViewSet, basename="reaction")

urlpatterns = [
    path("requisitions/<uuid:pk>/issue/", views.RequisitionViewSet.as_view({"post": "issue"}), name="requisition-issue")
]
