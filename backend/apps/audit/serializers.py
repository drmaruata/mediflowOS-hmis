"""Audit serializers."""
from rest_framework import serializers
from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = "__all__"
        read_only_fields = ["id", "occurred_at", "tenant_id"]


class AuditChainVerificationSerializer(serializers.Serializer):
    """Response of ``GET /audit-log/verify/`` (AUD-002).

    Declared rather than built inline so ``/api/docs/`` shows the exact shape
    the endpoint answers with: ``valid`` is the verdict, ``checked`` how many
    chained rows the pass recomputed, and ``first_bad`` the id of the row to
    look at first — ``None`` means the whole tenant chain verified.
    """

    valid = serializers.BooleanField()
    checked = serializers.IntegerField()
    first_bad = serializers.UUIDField(allow_null=True)
