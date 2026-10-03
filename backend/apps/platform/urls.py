"""Platform URLs."""
from rest_framework.routers import DefaultRouter

from . import views

app_name = "platform"

router = DefaultRouter()
router.register(r"notifications", views.NotificationViewSet, basename="notification")
router.register(r"files", views.PlatformFileViewSet, basename="platformfile")
router.register(r"scheduled-jobs", views.ScheduledJobViewSet, basename="scheduledjob")

urlpatterns = [*router.urls]
