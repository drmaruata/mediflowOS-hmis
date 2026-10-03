"""Quality OS serializers."""
from rest_framework import serializers
from .models import CAPA, Framework, FrameworkEdition, IndicatorDef, IndicatorSourceDocument, IndicatorValue, QualityFact


class FrameworkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Framework
        fields = "__all__"
        read_only_fields = ["id"]


class FrameworkEditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FrameworkEdition
        fields = "__all__"
        read_only_fields = ["id"]


class IndicatorSourceDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = IndicatorSourceDocument
        fields = "__all__"
        read_only_fields = ["id", "imported_at"]


class IndicatorDefSerializer(serializers.ModelSerializer):
    class Meta:
        model = IndicatorDef
        fields = "__all__"
        read_only_fields = ["id"]


class IndicatorValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = IndicatorValue
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class CAPASerializer(serializers.ModelSerializer):
    class Meta:
        model = CAPA
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class QualityFactSerializer(serializers.ModelSerializer):
    class Meta:
        model = QualityFact
        fields = "__all__"
        read_only_fields = ["id", "created_at", "tenant_id"]
