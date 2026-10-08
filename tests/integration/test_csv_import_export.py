"""CSV import/export for beds and staff positions (SET-013).

``GET /api/v1/beds/export/`` downloads the tenant's beds as a CSV attachment
(columns: ward, bed_number, functional, active — ward as its *name*, so the
import must resolve it back within the tenant); ``POST /api/v1/beds/import/``
takes a multipart upload of that same shape, validates every row against the
bed serializer AND the tenant-scoped ward table before writing anything, and
then writes all rows inside one explicit transaction — all-or-nothing per
request, answered ``{"created": n, "updated": m, "errors": [{"row", "reason"}]}``.
The same pair exists for staff positions (columns: department, designation,
specialty, sanctioned, in_position — department as name).

These tests pin the contract the brief calls out: the export contains only the
requesting tenant's rows; an import round-trips its own export without
duplicating beds; a row whose ward does not exist in the tenant lands in
``errors`` with zero rows written — even the valid rows of the same file;
a malformed upload answers 422 before any parsing; and a ward or department
name that belongs to another hospital is an error, never a silent cross-write.
"""
import csv
from datetime import date
import io
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.identity_tenancy.models import (
    Bed,
    Department,
    Facility,
    StaffPosition,
    Tenant,
    Ward,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT_A = uuid.UUID("a1111111-0000-4000-8000-000000000001")
TENANT_B = uuid.UUID("b2222222-0000-4000-8000-000000000002")

TEST_PASSWORD = "pw-for-tests-only"

BED_COLUMNS = ["ward", "bed_number", "functional", "active"]
STAFF_COLUMNS = ["department", "designation", "specialty", "sanctioned", "in_position"]


def _login(username, password=TEST_PASSWORD):
    """Issue a real access token through the API (same pattern as the other
    integration suites, so the claims come from production's serializer)."""
    response = APIClient().post(
        "/api/v1/auth/token/",
        {"username": username, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.content
    return response.json()["access"]


def _make_client(tenant_id, username, slug):
    """An authenticated client of one tenant, with no permission claims."""
    from apps.identity_tenancy.models import Role, UserMembership

    Tenant.objects.get_or_create(id=tenant_id, defaults={"name": slug, "slug": slug})
    user = get_user_model().objects.create_user(
        username=username, password=TEST_PASSWORD
    )
    role = Role.objects.create(tenant_id=tenant_id, name=f"role-{slug}", permissions=[])
    UserMembership.objects.create(
        user=user, tenant_id=tenant_id, role=role, active=True
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_login(username)}")
    return client


@pytest.fixture
def facility():
    """A tenant-A facility, so departments under it resolve."""
    Tenant.objects.create(id=TENANT_A, name="tenant-a", slug="tenant-a")
    return Facility.objects.create(
        tenant_id=TENANT_A, name="Main Campus", level="District Hospital"
    )


@pytest.fixture
def config_client(facility):
    """An authenticated tenant-A user."""
    return _make_client(TENANT_A, "config-admin-a", "tenant-a")


@pytest.fixture
def other_client():
    """An authenticated tenant-B user."""
    return _make_client(TENANT_B, "config-admin-b", "tenant-b")


def _tenant_facility(tenant_id, name):
    """A tenant (if absent) and a facility it owns, for consistent seeding."""
    Tenant.objects.get_or_create(
        id=tenant_id, defaults={"name": name, "slug": name.lower().replace(" ", "-")}
    )
    return Facility.objects.create(
        tenant_id=tenant_id, name=name, level="District Hospital"
    )


def _seed_ward(tenant_id, facility_id, ward_name):
    """One department + ward row for a tenant, created directly."""
    department = Department.objects.create(
        tenant_id=tenant_id,
        facility_id=facility_id,
        name="OPD",
        effective_from=date.today(),
    )
    return Ward.objects.create(
        tenant_id=tenant_id, department=department, name=ward_name, type_tag="Medical"
    )


def _seed_bed(tenant_id, ward, bed_number, *, functional=True, active=True):
    """One bed under an existing ward, created directly."""
    return Bed.objects.create(
        tenant_id=tenant_id,
        ward=ward,
        bed_number=bed_number,
        functional=functional,
        active=active,
    )


def _seed_department(tenant_id, facility_id, dept_name):
    """One department row for a tenant, created directly."""
    return Department.objects.create(
        tenant_id=tenant_id,
        facility_id=facility_id,
        name=dept_name,
        effective_from=date.today(),
    )


def _seed_position(tenant_id, department, designation, *, specialty="General Medicine", sanctioned=1, in_position=0):
    """One staff position under an existing department, created directly."""
    return StaffPosition.objects.create(
        tenant_id=tenant_id,
        department=department,
        designation=designation,
        specialty=specialty,
        sanctioned=sanctioned,
        in_position=in_position,
    )


def _upload_csv(client, url, csv_text):
    """POST one CSV document as a multipart import request."""
    return client.post(
        url,
        {
            "file": SimpleUploadedFile(
                "import.csv", csv_text.encode("utf-8"), content_type="text/csv"
            )
        },
        format="multipart",
    )


def _parse_csv_response(response):
    """Decode a CSV export response into a list of row dicts."""
    assert response.status_code == 200, response.content
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))


class TestBedCsv:
    """SET-013 beds: the fixed columns, tenant isolation, round trip, 422, no cross-write."""

    def test_export_returns_only_the_tenant_beds(self, config_client, other_client, facility):
        """An export contains the caller's beds and none of the other tenant's.

        Two tenants both name a ward "Ward A"; each export must show exactly
        its own rows, ordered by ward name then bed number so the document is
        deterministic and diffable. A shared ward name in the other hospital
        must not broaden the export.
        """
        ward_a = _seed_ward(TENANT_A, facility.id, "Ward A")
        _seed_bed(TENANT_A, ward_a, "A1")
        _seed_bed(TENANT_A, ward_a, "A2", functional=False)
        ward_b = _seed_ward(TENANT_A, facility.id, "Ward B")
        _seed_bed(TENANT_A, ward_b, "B1")
        b_facility = _tenant_facility(TENANT_B, "B Campus")
        _seed_bed(TENANT_B, _seed_ward(TENANT_B, b_facility.id, "Ward A"), "B1")

        response = config_client.get("/api/v1/beds/export/")
        assert response["Content-Type"] == "text/csv"
        assert "attachment" in response["Content-Disposition"]

        rows = _parse_csv_response(response)
        assert [list(row.keys()) for row in rows] and set(rows[0]) == set(BED_COLUMNS)
        assert [dict(row) for row in rows] == [
            {"ward": "Ward A", "bed_number": "A1", "functional": "true", "active": "true"},
            {"ward": "Ward A", "bed_number": "A2", "functional": "false", "active": "true"},
            {"ward": "Ward B", "bed_number": "B1", "functional": "true", "active": "true"},
        ]

        other_rows = _parse_csv_response(other_client.get("/api/v1/staff-positions/export/"))
        assert other_rows == []
        # Tenant B's bed "A1/Ward A" is not in tenant A's export.
        assert Bed.objects.filter(tenant_id=TENANT_B, bed_number="B1").exists()

    def test_import_round_trips_an_export_without_duplicating(self, config_client, facility):
        """Re-importing an export updates matching beds and creates nothing.

        The natural key is (ward, bed_number) within the tenant. After the
        database is mutated beneath the document, the import must restore the
        exported values from the file and leave exactly the same row count —
        asserted from the database, so a response that looks right cannot pass.
        """
        ward_a = _seed_ward(TENANT_A, facility.id, "Ward A")
        _seed_bed(TENANT_A, ward_a, "A1")
        _seed_bed(TENANT_A, ward_a, "A2", functional=False, active=True)

        exported = config_client.get("/api/v1/beds/export/")
        rows = _parse_csv_response(exported)
        assert len(rows) == 2

        for bed_number, functional, active in (
            ("A1", False, True),
            ("A2", False, False),
        ):
            bed = Bed.objects.get(tenant_id=TENANT_A, bed_number=bed_number)
            bed.functional = functional
            bed.active = active
            bed.save(update_fields=["functional", "active"])

        imported = _upload_csv(
            config_client, "/api/v1/beds/import/", exported.content.decode("utf-8")
        )
        assert imported.status_code == 200, imported.content
        assert imported.json() == {"created": 0, "updated": 2, "errors": []}

        assert Bed.objects.filter(tenant_id=TENANT_A).count() == 2
        a1 = Bed.objects.get(tenant_id=TENANT_A, bed_number="A1")
        a2 = Bed.objects.get(tenant_id=TENANT_A, bed_number="A2")
        assert (a1.functional, a1.active) == (True, True)
        # A2 was exported as (false, true) and the mutation to active=false
        # must be undone by the round trip.
        assert (a2.functional, a2.active) == (False, True)

    def test_import_creates_rows_for_unknown_bed_numbers(self, config_client, facility):
        """A (ward, bed_number) absent from the tenant is created, others updated."""
        ward_a = _seed_ward(TENANT_A, facility.id, "Ward A")
        _seed_bed(TENANT_A, ward_a, "A1")

        imported = _upload_csv(
            config_client,
            "/api/v1/beds/import/",
            "ward,bed_number,functional,active\n"
            "Ward A,A1,true,true\n"
            "Ward A,A9,false,true\n",
        )
        assert imported.status_code == 200, imported.content
        assert imported.json() == {"created": 1, "updated": 1, "errors": []}

        beds = {
            bed.bed_number: bed
            for bed in Bed.objects.filter(tenant_id=TENANT_A)
        }
        assert set(beds) == {"A1", "A9"}
        assert beds["A9"].functional is False
        assert beds["A9"].active is True

    def test_unknown_ward_row_errors_and_writes_nothing(self, config_client, facility):
        """One bad row refuses the whole file: errors carry it, zero rows land.

        A file mixing a valid row with a row naming a non-existent ward must
        write nothing at all — all-or-nothing per request — and answer 200
        with the bad row's errors, so a client can correct and retry the file.
        """
        ward_a = _seed_ward(TENANT_A, facility.id, "Ward A")
        _seed_bed(TENANT_A, ward_a, "A1")

        imported = _upload_csv(
            config_client,
            "/api/v1/beds/import/",
            "ward,bed_number,functional,active\n"
            "Ward A,A2,true,true\n"
            "No Such Ward,A3,true,true\n",
        )
        assert imported.status_code == 200, imported.content
        body = imported.json()
        assert body["created"] == 0
        assert body["updated"] == 0
        assert body["errors"] == [
            {"row": 2, "reason": "ward 'No Such Ward' does not exist in this tenant."}
        ]
        # Not even the valid row landed.
        assert Bed.objects.filter(tenant_id=TENANT_A).count() == 1
        assert not Bed.objects.filter(tenant_id=TENANT_A, bed_number="A2").exists()

    def test_ambiguous_ward_name_errors_and_writes_nothing(self, config_client, facility):
        """Two same-named wards refuse the row rather than pick one silently.

        Ward names are not unique within a tenant, so an import row naming an
        ambiguous ward must error — a silent guess could file a bed under the
        wrong ward, which is no better than a cross-write from the operator's
        point of view. Zero rows are written.
        """
        _seed_ward(TENANT_A, facility.id, "Ward A")
        _seed_ward(TENANT_A, facility.id, "Ward A")

        imported = _upload_csv(
            config_client,
            "/api/v1/beds/import/",
            "ward,bed_number,functional,active\n"
            "Ward A,A1,true,true\n",
        )
        assert imported.status_code == 200, imported.content
        body = imported.json()
        assert body["created"] == 0 and body["updated"] == 0
        assert body["errors"] == [
            {
                "row": 1,
                "reason": "ward name 'Ward A' is ambiguous: matches 2 rows.",
            }
        ]
        assert not Bed.objects.filter(tenant_id=TENANT_A).exists()

    def test_malformed_csv_answers_422(self, config_client, facility):
        """A document that is not a well-formed beds CSV is refused 422.

        Both shapes — undecodable bytes and a header row that does not match
        the fixed column set — are document-level failures, answered before
        any row is inspected, so an import can never silently proceed on a
        subset of the file.
        """
        ward_a = _seed_ward(TENANT_A, facility.id, "Ward A")
        _seed_bed(TENANT_A, ward_a, "A1")

        for payload in (b"\x00\xff not utf-8", b"ward,bed_number\nA\n"):
            response = config_client.post(
                "/api/v1/beds/import/",
                {"file": SimpleUploadedFile("bad.csv", payload, content_type="text/csv")},
                format="multipart",
            )
            assert response.status_code == 422, response.content
        assert Bed.objects.filter(tenant_id=TENANT_A).count() == 1

    def test_cross_tenant_ward_name_is_an_error_not_a_cross_write(self, config_client, facility):
        """A ward that exists only in tenant B is invisible to tenant A's import.

        The import resolves ward names against the caller's tenant alone, so a
        name owned by another hospital errors as unknown — tenant B's beds are
        untouched and tenant A writes nothing. Reading the outcome from the
        database keeps the proof about rows, not responses.
        """
        ward_a = _seed_ward(TENANT_A, facility.id, "Ward A")
        _seed_bed(TENANT_A, ward_a, "A1")
        b_facility = _tenant_facility(TENANT_B, "B Campus")
        _seed_bed(
            TENANT_B, _seed_ward(TENANT_B, b_facility.id, "B Private Ward"), "B1"
        )

        imported = _upload_csv(
            config_client,
            "/api/v1/beds/import/",
            "ward,bed_number,functional,active\n"
            "B Private Ward,B1,true,true\n",
        )
        assert imported.status_code == 200, imported.content
        body = imported.json()
        assert body["created"] == 0 and body["updated"] == 0
        assert body["errors"] == [
            {"row": 1, "reason": "ward 'B Private Ward' does not exist in this tenant."}
        ]
        assert Bed.objects.filter(tenant_id=TENANT_A).count() == 1
        # Tenant B's row still exists, exactly as it was seeded.
        assert Bed.objects.get(tenant_id=TENANT_B, bed_number="B1").functional is True

    def test_same_ward_name_in_both_tenants_resolves_within_tenant(self, config_client, facility):
        """A shared ward name resolves to the caller's ward, never the neighbour's.

        Both hospitals name a ward "Ward A"; tenant A imports a bed number that
        exists only in tenant B. The row must create a bed under A's "Ward A"
        and leave B's row untouched — proving the resolution was tenant-scoped
        rather than matched by string globally.
        """
        ward_a = _seed_ward(TENANT_A, facility.id, "Ward A")
        _seed_bed(TENANT_A, ward_a, "A1")
        b_facility = _tenant_facility(TENANT_B, "B Campus")
        _seed_bed(TENANT_B, _seed_ward(TENANT_B, b_facility.id, "Ward A"), "B1")

        imported = _upload_csv(
            config_client,
            "/api/v1/beds/import/",
            "ward,bed_number,functional,active\n"
            "Ward A,B1,true,true\n",
        )
        assert imported.status_code == 200, imported.content
        assert imported.json() == {"created": 1, "updated": 0, "errors": []}

        created = Bed.objects.get(tenant_id=TENANT_A, bed_number="B1")
        assert created.ward.name == "Ward A"
        # The resolution landed on tenant A's own ward, not the neighbour's
        # identically-named one.
        assert created.ward.tenant_id == TENANT_A
        assert created.ward.id == ward_a.id
        # Tenant B's own "Ward A"/B1 bed is untouched and unmodified.
        assert Bed.objects.filter(tenant_id=TENANT_B, bed_number="B1").count() == 1
        assert Bed.objects.filter(tenant_id=TENANT_B).count() == 1


class TestStaffPositionCsv:
    """SET-013 staff positions: derived columns, round trip, tenant-scoped department."""

    def test_export_columns_are_the_position_public_fields_without_active(self, config_client, facility):
        """The staff export has exactly the derived columns and no ``active``.

        ``StaffPosition`` carries no ``active`` field (Task 8 added it only to
        ``Bed``), so the export must not invent one; the column set is derived
        from the model: the department as its name plus the four public scalar
        fields, so import and export stay symmetric.
        """
        department = _seed_department(TENANT_A, facility.id, "OPD")
        _seed_position(
            TENANT_A,
            department,
            "Medical Officer",
            specialty="General Medicine",
            sanctioned=3,
            in_position=2,
        )

        rows = _parse_csv_response(config_client.get("/api/v1/staff-positions/export/"))
        assert set(rows[0]) == set(STAFF_COLUMNS)
        assert "active" not in rows[0]
        assert dict(rows[0]) == {
            "department": "OPD",
            "designation": "Medical Officer",
            "specialty": "General Medicine",
            "sanctioned": "3",
            "in_position": "2",
        }

    def test_staff_import_round_trips_an_export(self, config_client, facility):
        """Re-importing a staff export restores mutated rows without duplicates.

        The natural key is (department, designation) within the tenant,
        mirroring the model's (tenant_id, department, designation) index.
        """
        department = _seed_department(TENANT_A, facility.id, "OPD")
        _seed_position(TENANT_A, department, "Medical Officer", sanctioned=3, in_position=2)

        exported = config_client.get("/api/v1/staff-positions/export/")
        rows = _parse_csv_response(exported)
        assert len(rows) == 1

        row = StaffPosition.objects.get(tenant_id=TENANT_A, designation="Medical Officer")
        row.sanctioned = 5
        row.in_position = 4
        row.save(update_fields=["sanctioned", "in_position"])

        imported = _upload_csv(
            config_client,
            "/api/v1/staff-positions/import/",
            exported.content.decode("utf-8"),
        )
        assert imported.status_code == 200, imported.content
        assert imported.json() == {"created": 0, "updated": 1, "errors": []}

        assert StaffPosition.objects.filter(tenant_id=TENANT_A).count() == 1
        restored = StaffPosition.objects.get(tenant_id=TENANT_A, designation="Medical Officer")
        assert (restored.sanctioned, restored.in_position) == (3, 2)

    def test_unknown_department_row_errors_and_writes_nothing(self, config_client, facility):
        """A row naming a non-existent department errors and nothing imports."""
        department = _seed_department(TENANT_A, facility.id, "OPD")
        _seed_position(TENANT_A, department, "Medical Officer")

        imported = _upload_csv(
            config_client,
            "/api/v1/staff-positions/import/",
            "department,designation,specialty,sanctioned,in_position\n"
            "OPD,Nurse,General,3,2\n"
            "No Such Dept,Surgeon,General,1,1\n",
        )
        assert imported.status_code == 200, imported.content
        body = imported.json()
        assert body["created"] == 0 and body["updated"] == 0
        assert body["errors"] == [
            {"row": 2, "reason": "department 'No Such Dept' does not exist in this tenant."}
        ]
        assert not StaffPosition.objects.filter(tenant_id=TENANT_A, designation="Nurse").exists()
        assert StaffPosition.objects.filter(tenant_id=TENANT_A).count() == 1

    def test_cross_tenant_department_name_errors(self, config_client, facility):
        """A department owned only by tenant B never becomes tenant A's import."""
        department = _seed_department(TENANT_A, facility.id, "OPD")
        _seed_position(TENANT_A, department, "Medical Officer")
        b_facility = _tenant_facility(TENANT_B, "B Campus")
        _seed_position(
            TENANT_B, _seed_department(TENANT_B, b_facility.id, "B Only Dept"), "Surgeon"
        )

        imported = _upload_csv(
            config_client,
            "/api/v1/staff-positions/import/",
            "department,designation,specialty,sanctioned,in_position\n"
            "B Only Dept,Surgeon,General,1,1\n",
        )
        assert imported.status_code == 200, imported.content
        assert imported.json() == {
            "created": 0,
            "updated": 0,
            "errors": [
                {"row": 1, "reason": "department 'B Only Dept' does not exist in this tenant."}
            ],
        }
        assert StaffPosition.objects.get(tenant_id=TENANT_B, designation="Surgeon").sanctioned == 1
        # Tenant A's own staff list is untouched by the rejected file.
        assert [s.designation for s in StaffPosition.objects.filter(tenant_id=TENANT_A)] == ["Medical Officer"]

    def test_malformed_staff_csv_answers_422(self, config_client, facility):
        """A staff import with the wrong header shape is refused 422."""
        department = _seed_department(TENANT_A, facility.id, "OPD")
        _seed_position(TENANT_A, department, "Medical Officer")

        response = config_client.post(
            "/api/v1/staff-positions/import/",
            {"file": SimpleUploadedFile("bad.csv", b"department,designation\n", content_type="text/csv")},
            format="multipart",
        )
        assert response.status_code == 422, response.content
        assert StaffPosition.objects.filter(tenant_id=TENANT_A).count() == 1