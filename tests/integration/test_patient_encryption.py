"""Application-level field encryption at rest (REG-008).

``abha_number``, ``abha_address`` and ``contact.mobile`` are stored as AES-GCM
tokens (``v1:...``) and exposed as plaintext through the model and serializers.
REG-002 search and REG-003 duplicate detection therefore route through the
deterministic HMAC index columns (``abha_number_idx`` / ``mobile_idx``), never
through the ciphertext, and the ABDM gateway re-matches a returning scan via the
same index (ABD-008).

The at-rest assertions read the raw database columns through ``values()``
(which bypasses the model's decrypt-on-load), because a test that only re-reads
through the model could pass against a setup that decrypts everything in
memory and never writes a token.
"""
import json
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework.test import APIClient

from apps.identity_tenancy.models import (
    Department, Facility, Role, Tenant, UserMembership,
)
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.patient_registry.models import Patient
from common.crypto import TOKEN_PREFIX, decrypt, derive_keys, search_index

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_AES_KEY, _HMAC_KEY = derive_keys("kepi-12-unit-passphrase")


def _make_context(name="Encryption Hospital"):
    tenant = Tenant.objects.create(
        name=name, slug=f"enc-{uuid.uuid4().hex[:8]}"
    )
    facility = Facility.objects.create(
        tenant=tenant, name="Main Campus",
        abdm_hip_id=f"HIP-ENC-{uuid.uuid4().hex[:6].upper()}",
    )
    department = Department.objects.create(
        tenant=tenant, facility=facility, name="Medicine",
        effective_from="2026-01-01", opd_enabled=True,
    )
    return tenant, facility, department


def _make_client(tenant, facility, username="reception"):
    user = get_user_model().objects.create_user(
        username=username, password="testpass123"
    )
    role = Role.objects.create(tenant=tenant, name=f"role-{username}", permissions=[])
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    refresh = TenantAwareTokenSerializer.get_token(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


def _raw_row(patient_id):
    """The columns as the database stores them, bypassing decrypt-on-load."""
    return Patient.objects.values(
        "_abha_number", "_abha_address", "contact",
        "abha_number_idx", "abha_address_idx", "mobile_idx",
    ).get(pk=patient_id)


class TestAtRestEncryption:
    """Sensitive identifiers are tokens in the database, plaintext on the model."""

    def test_columns_hold_tokens_not_plaintext(self):
        tenant, _, _ = _make_context()
        plain = {
            "abha_number": "123456789012",
            "abha_address": "patient@abdm",
            "contact": {"mobile": "9876543210"},
        }
        patient = Patient.objects.create(
            tenant_id=tenant.id, uhid="UHID-ENC-1",
            demographics={"name": "Enc At Rest", "gender": "F", "yearOfBirth": 1981},
            **plain,
        )

        raw = _raw_row(patient.id)
        assert raw["_abha_number"].startswith(TOKEN_PREFIX)
        assert raw["_abha_address"].startswith(TOKEN_PREFIX)
        assert raw["contact"]["mobile"].startswith(TOKEN_PREFIX)
        stored = json.dumps(raw)
        assert plain["abha_number"] not in stored
        assert plain["abha_address"] not in stored
        assert plain["contact"]["mobile"] not in stored

    def test_index_columns_are_deterministic_hmacs(self):
        tenant, _, _ = _make_context()
        patient = Patient.objects.create(
            tenant_id=tenant.id, uhid="UHID-ENC-2",
            demographics={"name": "Enc Index", "gender": "M", "yearOfBirth": 1979},
            abha_number="123456789012",
            contact={"mobile": "9876543210"},
        )
        raw = _raw_row(patient.id)
        assert raw["abha_number_idx"] == search_index(
            "123456789012", key=_HMAC_KEY
        )
        assert raw["mobile_idx"] == search_index("9876543210", key=_HMAC_KEY)

    def test_model_reads_return_plaintext(self):
        tenant, _, _ = _make_context()
        patient = Patient.objects.create(
            tenant_id=tenant.id, uhid="UHID-ENC-3",
            demographics={"name": "Enc Read", "gender": "F", "yearOfBirth": 1983},
            abha_number="123456789012",
            abha_address="patient@abdm",
            contact={"mobile": "9876543210"},
        )

        fresh = Patient.objects.get(pk=patient.id)
        assert fresh.abha_number == "123456789012"
        assert fresh.abha_address == "patient@abdm"
        assert fresh.contact["mobile"] == "9876543210"

    def test_persistent_instance_mobile_is_a_valid_token(self):
        """The stored token must actually decrypt to the plaintext (REG-008)."""
        tenant, _, _ = _make_context()
        patient = Patient.objects.create(
            tenant_id=tenant.id, uhid="UHID-ENC-4",
            demographics={"name": "Enc Verify", "gender": "M", "yearOfBirth": 1977},
            contact={"mobile": "9876543210"},
        )
        raw = _raw_row(patient.id)
        assert decrypt(raw["contact"]["mobile"], key=_AES_KEY) == "9876543210"
        # The ABHA column is unset for this row (NULL), which is a legal state.


class TestIndexBasedLookupHelpers:
    """filter_by_mobile / filter_by_abha route through the HMAC columns."""

    def test_filter_by_mobile_and_abha_find_the_patient(self):
        tenant, _, _ = _make_context()
        patient = Patient.objects.create(
            tenant_id=tenant.id, uhid="UHID-HELPER-1",
            demographics={"name": "Helper", "gender": "F", "yearOfBirth": 1985},
            abha_number="123456789012",
            contact={"mobile": "9876543210"},
        )

        by_mobile = Patient.objects.filter_by_mobile(tenant.id, "9876543210")
        assert list(by_mobile) == [patient]
        by_abha = Patient.objects.filter_by_abha(tenant.id, "123456789012")
        assert list(by_abha) == [patient]

    def test_helpers_never_see_another_tenant(self):
        tenant_a, _, _ = _make_context()
        tenant_b, _, _ = _make_context("Other Hospital")
        Patient.objects.create(
            tenant_id=tenant_a.id, uhid="UHID-TENANT-A",
            demographics={"name": "Tenant A", "gender": "M", "yearOfBirth": 1975},
            abha_number="123456789012",
            contact={"mobile": "9876543210"},
        )

        assert list(Patient.objects.filter_by_mobile(tenant_b.id, "9876543210")) == []
        assert list(Patient.objects.filter_by_abha(tenant_b.id, "123456789012")) == []

    def test_helpers_miss_on_wrong_probe(self):
        tenant, _, _ = _make_context()
        Patient.objects.create(
            tenant_id=tenant.id, uhid="UHID-HELPER-2",
            demographics={"name": "Helper Two", "gender": "F", "yearOfBirth": 1986},
            contact={"mobile": "9876543210"},
        )
        assert list(Patient.objects.filter_by_mobile(tenant.id, "9000000000")) == []
        assert list(Patient.objects.filter_by_abha(tenant.id, "999999999999")) == []


class TestSearchThroughIndex:
    """REG-002 search finds encrypted rows via the index columns."""

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client = _make_client(self.tenant, self.facility)
        self.patient = Patient.objects.create(
            tenant_id=self.tenant.id,
            uhid="UHID-SEARCH-ENC",
            demographics={"name": "Searchable", "gender": "F", "yearOfBirth": 1988},
            abha_number="123456789012",
            abha_address="search@abdm",
            contact={"mobile": "9876543210"},
        )

    def test_mobile_query_param_finds_the_patient(self):
        response = self.client.get("/api/v1/patients/search/?mobile=9876543210")
        assert response.status_code == 200, response.content
        assert {row["uhid"] for row in response.json()} == {"UHID-SEARCH-ENC"}

    def test_mobile_param_with_country_prefix_still_matches(self):
        """A formatted probe is canonicalised before it hits the index."""
        response = self.client.get("/api/v1/patients/search/?mobile=%2B91%2098765%2043210")
        assert response.status_code == 200, response.content
        assert {row["uhid"] for row in response.json()} == {"UHID-SEARCH-ENC"}

    def test_q_finds_mobile_abha_number_and_abha_address(self):
        for term in ("9876543210", "123456789012", "search@abdm"):
            response = self.client.get(
                f"/api/v1/patients/search/?q={term}"
            )
            assert response.status_code == 200, response.content
            assert {row["uhid"] for row in response.json()} == {"UHID-SEARCH-ENC"}, term

    def test_abha_number_param_finds_the_patient(self):
        response = self.client.get("/api/v1/patients/search/?abha_number=123456789012")
        assert response.status_code == 200, response.content
        assert {row["uhid"] for row in response.json()} == {"UHID-SEARCH-ENC"}

    def test_partial_identifier_is_no_longer_a_substring_match(self):
        """A phone/ABHA fragment cannot match through the HMAC index.

        The index is an exact deterministic digest, so a *containment* probe
        ("find 9876") has nothing to match — the previous ``icontains`` lookup
        is impossible on ciphertext. This pins the deliberate degradation so a
        future change cannot accidentally reintroduce plaintext scanning.
        """
        response = self.client.get("/api/v1/patients/search/?q=9876")
        assert response.status_code == 200, response.content
        assert all(row["uhid"] != "UHID-SEARCH-ENC" for row in response.json())

    def test_serializer_output_is_plaintext(self):
        response = self.client.get(
            "/api/v1/patients/search/?q=9876543210"
        )
        body = response.json()[0]
        assert body["abha_number"] == "123456789012"
        assert body["abha_address"] == "search@abdm"
        assert body["contact"]["mobile"] == "9876543210"


class TestDuplicateCheckThroughIndex:
    """REG-003 duplicate probes find encrypted rows via the index columns."""

    def test_abha_and_mobile_probes_find_encrypted_rows(self):
        tenant, _, facility = _make_context()
        client = _make_client(tenant, facility)
        Patient.objects.create(
            tenant_id=tenant.id, uhid="UHID-DUP-ENC",
            demographics={"name": "Probe Me", "gender": "M", "yearOfBirth": 1984},
            abha_number="123456789012",
            contact={"mobile": "9876543210"},
        )

        abha = client.post(
            "/api/v1/patients/duplicate-check/",
            {"name": "Probe Me", "dob": "1984-01-01", "abha_number": "123456789012"},
            format="json",
        )
        assert abha.status_code == 200, abha.content
        assert [row["uhid"] for row in abha.json()["candidates"]] == ["UHID-DUP-ENC"]

        mobile = client.post(
            "/api/v1/patients/duplicate-check/",
            {"name": "Probe Me", "dob": "1984-01-01", "mobile": "+91 98765 43210"},
            format="json",
        )
        assert mobile.status_code == 200, mobile.content
        assert [row["uhid"] for row in mobile.json()["candidates"]] == ["UHID-DUP-ENC"]


class TestAbdmCallbackRematchesEncryptedPatient:
    """A returning ABDM scan matches the encrypted row via the index (ABD-008)."""

    def test_second_scan_returns_same_patient_no_duplicate_row(self):
        tenant = Tenant.objects.create(
            name="ABDM Enc", slug=f"abdm-enc-{uuid.uuid4().hex[:8]}"
        )
        facility = Facility.objects.create(
            tenant=tenant, name="Main Campus", abdm_hip_id="hip-enc-1",
        )
        Department.objects.create(
            tenant=tenant, facility=facility, name="Medicine",
            effective_from="2026-01-01", opd_enabled=True,
        )

        gateway = APIClient()
        auth = {"HTTP_X_AUTHORIZATION": "gateway-shared-secret"}
        from django.utils import timezone

        payload = {
            "requestId": "req-enc-1",
            "facilityId": "hip-enc-1",
            "timestamp": timezone.now().isoformat(),
            "profile": {"abhaNumber": "123456789012"},
        }

        first = gateway.post("/api/v1/abdm-callbacks/", payload, format="json", **auth)
        assert first.status_code == 200, first.content
        patient_id = first.json()["patient_id"]
        second = gateway.post("/api/v1/abdm-callbacks/", payload, format="json", **auth)

        assert second.status_code == 200, second.content
        assert second.json()["patient_id"] == patient_id
        assert Patient.objects.count() == 1


class TestPatientFieldEncryptionMigration:
    """The 0010 data ops encrypt/decrypt in place (REG-008).

    The reverse operation is what keeps the migration a true expand-and-revert:
    a rollback must put the stored values back to plaintext, not strand tokens
    that post-0010 code could not read.
    """

    def _plaintext_row(self, tenant_id, uhid):
        patient = Patient.objects.create(
            tenant_id=tenant_id, uhid=uhid,
            demographics={"name": "Legacy", "gender": "F", "yearOfBirth": 1970},
            abha_number="123456789012",
            abha_address="legacy@abdm",
            contact={"mobile": "9876543210"},
        )
        # Simulate a row as it existed *before* 0010: every sensitive column
        # holds plaintext. Raw SQL bypasses the real model's transparent
        # encryption so the migration function sees the pre-encryption state.
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE "registry.patient" SET "abha_number"=%s, '
                '"abha_address"=%s, "abha_number_idx"=%s, "abha_address_idx"=%s, '
                '"mobile_idx"=%s, "contact"=%s WHERE "id"=%s',
                [
                    "123456789012",
                    "legacy@abdm",
                    "",
                    "",
                    "",
                    json.dumps({"mobile": "9876543210"}),
                    str(patient.id),
                ],
            )
        return patient

    def test_forward_encrypts_existing_plaintext_rows(self):
        from importlib import import_module

        from django.apps import apps

        migration = import_module(
            "apps.patient_registry.migrations.0010_patient_field_encryption"
        )
        tenant, _, _ = _make_context()
        patient = self._plaintext_row(tenant.id, "UHID-MIG-1")

        migration.encrypt_existing_rows(apps, None)

        patient.refresh_from_db()
        assert patient.abha_number == "123456789012"
        assert patient.abha_address == "legacy@abdm"
        assert patient.contact["mobile"] == "9876543210"
        raw = _raw_row(patient.id)
        assert raw["_abha_number"].startswith(TOKEN_PREFIX)
        assert raw["_abha_address"].startswith(TOKEN_PREFIX)
        assert raw["contact"]["mobile"].startswith(TOKEN_PREFIX)
        assert raw["mobile_idx"] == search_index("9876543210", key=_HMAC_KEY)

    def test_forward_is_idempotent_for_already_encrypted_rows(self):
        from importlib import import_module

        from django.apps import apps

        migration = import_module(
            "apps.patient_registry.migrations.0010_patient_field_encryption"
        )
        tenant, _, _ = _make_context()
        patient = self._plaintext_row(tenant.id, "UHID-MIG-2")

        migration.encrypt_existing_rows(apps, None)
        raw_first = _raw_row(patient.id)
        migration.encrypt_existing_rows(apps, None)
        raw_second = _raw_row(patient.id)

        assert raw_first["_abha_number"] == raw_second["_abha_number"]
        assert raw_first["contact"]["mobile"] == raw_second["contact"]["mobile"]

    def test_reverse_restores_plaintext(self):
        from importlib import import_module

        from django.apps import apps

        migration = import_module(
            "apps.patient_registry.migrations.0010_patient_field_encryption"
        )
        tenant, _, _ = _make_context()
        patient = self._plaintext_row(tenant.id, "UHID-MIG-3")

        migration.encrypt_existing_rows(apps, None)
        migration.decrypt_existing_rows(apps, None)

        patient.refresh_from_db()
        assert patient.abha_number == "123456789012"
        assert patient.contact["mobile"] == "9876543210"
        raw = _raw_row(patient.id)
        assert raw["_abha_number"] == "123456789012"
        assert raw["contact"]["mobile"] == "9876543210"