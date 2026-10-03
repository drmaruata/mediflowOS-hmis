"""Pharmacy URLs."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "pharmacy"

router = DefaultRouter()
router.register(r"formulary", views.FormularyViewSet, basename="formulary")
router.register(r"stock-batches", views.StockBatchViewSet, basename="stockbatch")
router.register(r"dispenses", views.DispenseViewSet, basename="dispense")

urlpatterns = [
    path("stockouts/", views.StockBatchViewSet.as_view({"get": "stockouts"}), name="stockouts")
]
