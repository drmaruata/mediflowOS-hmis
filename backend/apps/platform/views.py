"""Platform views."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import Notification, PlatformFile, ScheduledJob
from .serializers import NotificationSerializer, PlatformFileSerializer, ScheduledJobSerializer

logger = logging.getLogger(__name__)


def _push_notification(tenant_id, payload):
    """Deliver a notification to the tenant's connected sockets (PLT-001, INT-012).

    The channel layer is async and the view is not, hence ``async_to_sync``.

    A push failure is logged and swallowed rather than raised. The row is already
    committed by the time this runs, so an exception here would answer 500 for a
    write that actually succeeded - the client, seeing an error, retries and the
    alert is duplicated, which is the worse failure for a clinical notification.
    A persisted-but-not-pushed row is still recoverable: the client polls on
    reload, and the row's ``delivered`` flag records what never went out.
    """
    layer = get_channel_layer()
    if layer is None:
        logger.error(
            "notification push skipped: no channel layer is configured "
            "(CHANNEL_LAYERS)"
        )
        return
    try:
        async_to_sync(layer.group_send)(
            f"tenant_{tenant_id}",
            {"type": "send_notification", "payload": payload},
        )
    except Exception:
        logger.exception("notification push failed tenant_id=%s", tenant_id)


class NotificationViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """In-app notifications (PLT-001)."""
    serializer_class = NotificationSerializer
    queryset = Notification.objects.all()

    def perform_create(self, serializer):
        """Persist the notification, then push it to the tenant's sockets.

        ``persisted`` is stamped here, never taken from the client: a create
        through this API is by definition an in-app notification, so it has to
        survive a reload. The push is what makes the consumer's ``delivered``
        flag mean anything - before it existed no socket ever heard about a row,
        so nothing could ever set the flag.
        """
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        notification = serializer.save(**{"tenant_id": tenant_id, "persisted": True})
        _push_notification(str(tenant_id), NotificationSerializer(notification).data)

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
