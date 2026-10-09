"""Patient registry serializers."""
import re

from rest_framework import serializers

from .models import Patient, IntakePoint, QRCode

#: 10-digit Indian mobile, first digit 6-9. Chosen over a ``+91``-anchored
#: pattern because the stored form is the bare national number; a leading
#: ``+91``/``91``/``0`` is stripped before the match so callers may send either
#: form. Complains on letters, short numbers, and landline-style leading zeros.
MOBILE_RE = re.compile(r"^[6-9]\d{9}$")

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


def _normalise_mobile(value) -> str:
    """Strip a ``+91``/``91``/``0`` prefix and non-digits, leaving 10 digits."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("0"):
        digits = digits[1:]
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits


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
        """A supplied mobile must be a valid Indian mobile (REG-007)."""
        if value is None:
            return value
        if not isinstance(value, dict):
            raise serializers.ValidationError("Contact must be an object.")
        mobile = value.get("mobile")
        if mobile not in (None, "") and not MOBILE_RE.fullmatch(
            _normalise_mobile(mobile)
        ):
            raise serializers.ValidationError(
                "Enter a 10-digit Indian mobile number (optionally prefixed +91)."
            )
        return value

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
    class Meta:
        model = QRCode
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
