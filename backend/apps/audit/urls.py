"""Audit URLs."""
from rest_framework.routers import DefaultRouter

from . import views

app_name = "audit"

router = DefaultRouter()
router.register(r"audit-log", views.AuditLogViewSet, basename="auditlog")

urlpatterns = [*router.urls]
