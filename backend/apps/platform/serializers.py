"""Platform serializers."""
from rest_framework import serializers
from .models import Notification, PlatformFile, ScheduledJob


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = "__all__"
        # ``persisted`` and ``delivered`` are server-owned and belong in
        # read_only_fields for the same reason ``tenant_id`` does: a caller who
        # could write them could mark an alert as stored and received without
        # either having happened - the view persists what it creates and the
        # WebSocket consumer sets delivered when a socket actually receives the
        # row (PLT-001).
        read_only_fields = [
            "id",
            "created_at",
            "tenant_id",
            "persisted",
            "delivered",
        ]


class PlatformFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformFile
        fields = "__all__"
        read_only_fields = ["id", "uploaded_at", "tenant_id"]


class ScheduledJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduledJob
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
