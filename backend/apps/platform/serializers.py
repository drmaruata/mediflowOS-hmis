"""Platform serializers."""
from rest_framework import serializers
from .models import Notification, PlatformFile, ScheduledJob


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = "__all__"
        read_only_fields = ["id", "created_at", "tenant_id"]


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
