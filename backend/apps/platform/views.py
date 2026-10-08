"""Platform views."""
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import Notification, PlatformFile, ScheduledJob
from .serializers import NotificationSerializer, PlatformFileSerializer, ScheduledJobSerializer


class NotificationViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """In-app notifications (PLT-001)."""
    serializer_class = NotificationSerializer
    queryset = Notification.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @action(detail=False, methods=["get"])
    def unread(self, request):
        """List unread notifications."""
        queryset = self.get_queryset().filter(read_at__isnull=True)
        return Response(NotificationSerializer(queryset, many=True).data)

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Mark a notification as read."""
        notification = self.get_object()
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
        return Response(NotificationSerializer(notification).data)


class PlatformFileViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """File storage with access control (PLT-005)."""
    serializer_class = PlatformFileSerializer
    queryset = PlatformFile.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})


class ScheduledJobViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """Background job visibility (PLT-004), scoped to the request's tenant (TEN-002)."""
    serializer_class = ScheduledJobSerializer
    queryset = ScheduledJob.objects.all()
