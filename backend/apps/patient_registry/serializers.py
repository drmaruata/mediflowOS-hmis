"""Patient registry serializers."""
from rest_framework import serializers

from apps.identity_tenancy.models import Department
from common.tenant import REQUEST_TENANT_ATTR
from .models import Patient, IntakePoint, QRCode
from .validation import MOBILE_RE, normalise_mobile

#: Birth-data keys accepted in ``demographics`` (REG-007). ``yearOfBirth`` is
#: the established registry key; ``dob``/``age_years`` are the documented
#: contract. A registration must carry one of them, or it cannot be matched
#: against a probable duplicate (REG-003).
BIRTH_KEYS = ("dob", "age_years", "yearOfBirth", "year_of_birth")

#: Consent flag keys the platform actually records. The SRS states the consent
#: requirement (REG-007) but does not enumerate key names; the ABDM gateway is
#: the only producer today and writes ``abdm_scan_and_share``, so that is the
#: documented set. New keys are added here alongside their producer.
CONSENT_FLAG_KEYS = frozenset({"abdm_scan_and_share"})


class PatientSerializer(serializers.ModelSerializer):
    #: Write-only intake department for the registration counter (REG-010):
    #: when present, the view mints an OPD token for that department and
    #: returns it as the response-level ``token`` object, never inside the
    #: patient representation itself.
    intake_department_id = serializers.UUIDField(
        write_only=True, required=False, allow_null=True
    )

    # REG-008: ``abha_number``/``abha_address`` are model *properties* over
    # encrypted storage columns, so DRF's model introspection cannot build
    # fields for them. Declared explicitly as writable plaintext CharFields:
    # the encrypting property setters seal the value on assignment, and the
    # response carries plaintext via the decrypting getter. ``allow_blank`` +
    # ``allow_null`` mirror the old ``CharField(blank=True, null=True)``.
    abha_number = serializers.CharField(
        max_length=128, required=False, allow_null=True, allow_blank=True
    )
    abha_address = serializers.CharField(
        max_length=128, required=False, allow_null=True, allow_blank=True
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
            "intake_channel",
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

    def validate_demographics(self, value):
        """Require identity and birth data on the registration payload (REG-007).

        A record with no name, no gender, or no way to establish age cannot be
        matched for duplicates (REG-003) or safely identified later, so it is
        refused at the field rather than stored half-formed.
        """
        if not isinstance(value, dict):
            raise serializers.ValidationError("Demographics must be an object.")
        if not str(value.get("name") or "").strip():
            raise serializers.ValidationError("A patient name is required.")
        if not str(value.get("gender") or "").strip():
            raise serializers.ValidationError("A gender is required.")
        if not any(value.get(key) not in (None, "") for key in BIRTH_KEYS):
            raise serializers.ValidationError(
                "A date of birth or age is required (dob, age_years or yearOfBirth)."
            )
        return value

    def validate_contact(self, value):
        """A supplied mobile must be a valid Indian mobile; store it canonically.

        REG-007 accepts ``+91``/spacing, but REG-003's duplicate prefilter is a
        substring lookup on the *stored* value, so the mobile is reduced to the
        bare 10-digit national form on write (via :func:`normalise_mobile`). A
        registration that stored the client's formatted string verbatim was
        invisible to a later bare-digit probe. Other contact keys pass through
        untouched, and a missing mobile is not rewritten.
        """
        if value is None:
            return value
        if not isinstance(value, dict):
            raise serializers.ValidationError("Contact must be an object.")
        mobile = value.get("mobile")
        if mobile in (None, ""):
            return value
        canonical = normalise_mobile(mobile)
        if not MOBILE_RE.fullmatch(canonical):
            raise serializers.ValidationError(
                "Enter a 10-digit Indian mobile number (optionally prefixed +91)."
            )
        return {**value, "mobile": canonical}

    def validate_consent_flags(self, value):
        """Only documented, boolean consent flags may be recorded (REG-007)."""
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Consent flags must be an object.")
        unknown = set(value) - CONSENT_FLAG_KEYS
        if unknown:
            raise serializers.ValidationError(
                "Unknown consent flag(s): " + ", ".join(sorted(unknown)) + "."
            )
        for key, flag in value.items():
            if not isinstance(flag, bool):
                raise serializers.ValidationError(
                    f"Consent flag '{key}' must be true or false."
                )
        return value


class IntakePointSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntakePoint
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]


class QRCodeSerializer(serializers.ModelSerializer):
    # Explicitly declared rather than the field ModelSerializer would generate,
    # because the generated PrimaryKeyRelatedField's queryset is unscoped and
    # would accept another hospital's department id. ``validate_department``
    # pins the FK inside the request's tenant; the reading side stays the
    # plain UUID the generated field would have produced.
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = QRCode
        fields = "__all__"
        # encode_data is minted by QRCodeViewSet._encode_data from the row's
        # own facility/intake_point/department (REG-013); client-supplied
        # values must be ignored, never stored.
        read_only_fields = ["id", "tenant_id", "encode_data"]

    def validate_department(self, value):
        """A QR's department must belong to the tenant making the request.

        The QR names the department the scan should route to, so an accepted
        foreign id would mint callbacks into another hospital's queues.
        """
        if value is None:
            return value
        request = self.context.get("request")
        tenant_id = getattr(request, REQUEST_TENANT_ATTR, None) if request else None
        if tenant_id and str(value.tenant_id) != str(tenant_id):
            raise serializers.ValidationError(
                "Department must belong to the current tenant."
            )
        return value


class OpSlipTokenSerializer(serializers.Serializer):
    """The token block of the OP slip print contract (REG-011, REG-012).

    ``series``/``number`` are printed on the paper slip verbatim; they come
    from the ``opd.Token`` row ``OpSlipView`` selects for the visit.
    """

    series = serializers.CharField()
    number = serializers.IntegerField()


class OpSlipSerializer(serializers.Serializer):
    """JSON print contract for an OPD visit slip (REG-011, REG-012).

    A response-only serializer: every field is the denormalised value a paper
    slip shows — the patient's UHID and name, the department and facility
    display names, the token block, and the issue/visit dates. ``token`` and
    ``issued_at`` are null when the visit has no issued token (an encounter
    without a token still has a printable patient + visit core).
    """

    uhid = serializers.CharField()
    patient_name = serializers.CharField()
    token = OpSlipTokenSerializer(required=False, allow_null=True)
    department = serializers.CharField()
    facility = serializers.CharField()
    issued_at = serializers.DateTimeField(required=False, allow_null=True)
    visit_date = serializers.DateField()
