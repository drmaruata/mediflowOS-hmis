"""Integration serializers."""
from rest_framework import serializers
from .models import IntegrationAdapter, WebhookEndpoint


class IntegrationAdapterSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationAdapter
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at", "tenant_id"]


class WebhookEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEndpoint
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
