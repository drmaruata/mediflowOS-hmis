"""OPD serializers."""
from rest_framework import serializers
from .models import OPDEncounter, Token


class TokenSerializer(serializers.ModelSerializer[Token]):
    class Meta:
        model = Token
        fields = "__all__"
        read_only_fields = ["id", "issued_at", "tenant_id"]


class OPDEncounterSerializer(serializers.ModelSerializer[OPDEncounter]):
    class Meta:
        model = OPDEncounter
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
