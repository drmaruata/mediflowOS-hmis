"""Patient registry serializers."""
from rest_framework import serializers

from .models import Patient, IntakePoint, QRCode


class PatientSerializer(serializers.ModelSerializer):
    #: Write-only intake department for the registration counter (REG-010):
    #: when present, the view mints an OPD token for that department and
    #: returns it as the response-level ``token`` object, never inside the
    #: patient representation itself.
    intake_department_id = serializers.UUIDField(
        write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Patient
        fields = [
            "id",
            "tenant_id",
            "uhid",
            "abha_address",
            "abha_number",
            "verification_status",
            "verified_at",
            "demographics",
            "contact",
            "address",
            "scheme_category",
            "consent_flags",
            "created_at",
            "intake_department_id",
        ]
        # Server-owned (REG-001): uhid is minted by generate_uhid in
        # perform_create, verification_status/verified_at are flipped only by
        # the verify action, and created_at is audit data. A client-supplied
        # uhid must be ignored, never stored.
        read_only_fields = [
            "id",
            "tenant_id",
            "uhid",
            "verification_status",
            "verified_at",
            "created_at",
        ]


class IntakePointSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntakePoint
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class QRCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = QRCode
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
