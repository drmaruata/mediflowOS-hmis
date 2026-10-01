from rest_framework.routers import DefaultRouter
from . import views

app_name = "identity"

router = DefaultRouter()
router.register(r"tenants", views.TenantViewSet, basename="tenant")
router.register(r"facilities", views.FacilityViewSet, basename="facility")
router.register(r"departments", views.DepartmentViewSet, basename="department")
router.register(r"wards", views.WardViewSet, basename="ward")
router.register(r"beds", views.BedViewSet, basename="bed")
router.register(r"service-units", views.ServiceUnitViewSet, basename="serviceunit")
router.register(r"staff-positions", views.StaffPositionViewSet, basename="staffposition")

urlpatterns = router.urls
