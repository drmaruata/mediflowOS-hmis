"""Emergency serializers."""
from rest_framework import serializers
from .models import Triage


class TriageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Triage
        fields = "__all__"
        read_only_fields = ["id", "triage_time", "tenant_id"]
