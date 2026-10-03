"""Audit serializers."""
from rest_framework import serializers
from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = "__all__"
        read_only_fields = ["id", "occurred_at", "tenant_id"]
