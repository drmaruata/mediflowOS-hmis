"""Tenant scoping on the API surface.

``TenantScopedQuerysetMixin`` is the application-level half of isolation; row
level security is the database-level half. These tests pin down the first,
including the case that matters most - that an unresolved tenant yields an
empty result rather than every tenant's rows.
"""
import uuid

import pytest
from rest_framework.test import APIClient

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def user(django_user_model):
    """An authenticated principal.

    Every endpoint here is ``IsAuthenticated`` since the deny-by-default change,
    so the client must present a user before tenant scoping is even reached.
    """
    return django_user_model.objects.create_user(
        username="clerk", password="not-used-forced-auth"
    )


@pytest.fixture
def two_tenants():
    """Two tenants, each with one patient."""
    from apps.identity_tenancy.models import Tenant
    from apps.patient_registry.models import Patient

    for index, tenant_id in enumerate((TENANT_A, TENANT_B), start=1):
        Tenant.objects.create(id=tenant_id, name=f"Hospital {index}", slug=f"hosp-{index}")
        Patient.objects.create(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            uhid=f"UH{index:04d}",
            demographics={"name": f"Patient {index}"},
        )


def _client_for(tenant_id, user):
    client = APIClient()
    client.force_authenticate(user=user)
    if tenant_id is not None:
        client.credentials(HTTP_X_TENANT_ID=str(tenant_id))
    return client


class TestTenantScopedReads:
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/api/v1/patients/",
            "/api/v1/intake-points/",
            "/api/v1/wards/",
            "/api/v1/beds/",
            "/api/v1/departments/",
            "/api/v1/facilities/",
        ],
    )
    def test_list_only_returns_the_requesting_tenants_rows(self, two_tenants, user, endpoint):
        """The response must contain no other tenant's identifiers."""
        response = _client_for(TENANT_A, user).get(endpoint)

        assert response.status_code == 200
        # With only patients seeded, a leak-free tenant-scoped endpoint returns
        # nothing for the other resource types, and patients returns one row.
        body = str(response.json())
        assert "Hospital 2" not in body
        assert "UH0002" not in body

    def test_patient_list_is_scoped(self, two_tenants, user):
        response = _client_for(TENANT_A, user).get("/api/v1/patients/")

        assert response.status_code == 200
        assert [row["uhid"] for row in response.json()["results"]] == ["UH0001"]

    def test_other_tenant_switches_the_result_set(self, two_tenants, user):
        response = _client_for(TENANT_B, user).get("/api/v1/patients/")

        assert [row["uhid"] for row in response.json()["results"]] == ["UH0002"]


class TestUnresolvedTenantFailsClosed:
    def test_list_is_empty_without_a_tenant_header(self, two_tenants, user):
        """No tenant resolved must mean no rows.

        Returning everything would be the dangerous failure: it would look like
        a working endpoint while leaking every tenant.
        """
        response = _client_for(None, user).get("/api/v1/patients/")

        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_detail_lookup_by_pk_is_still_blocked(self, two_tenants, user):
        """Reading tenant-owned data by primary key alone is a defect.

        The id is a valid UUID from the other tenant; scoping must hide it.
        """
        from apps.patient_registry.models import Patient

        other_tenant_patient = Patient.objects.get(tenant_id=TENANT_B)

        response = _client_for(TENANT_A, user).get(f"/api/v1/patients/{other_tenant_patient.pk}/")

        assert response.status_code == 404

    def test_write_without_a_tenant_is_refused(self, two_tenants, user):
        response = _client_for(None, user).post(
            "/api/v1/patients/",
            {"uhid": "UH9999", "demographics": {"name": "No Tenant"}},
            format="json",
        )

        assert response.status_code in (400, 403)


class TestClientSuppliedTenantIsIgnored:
    def test_cannot_write_into_another_tenant(self, two_tenants, user):
        """A body claiming another tenant must not override the request context.

        Without this, tenant scoping would be advisory: any client could set
        ``tenant_id`` on create and write into a competitor's tenant.
        """
        response = _client_for(TENANT_A, user).post(
            "/api/v1/patients/",
            {
                # Fresh UHID, so the assertion below is about the tenant and not
                # a uniqueness collision with the fixture.
                "uhid": "UH7777",
                "tenant_id": str(TENANT_B),
                "demographics": {"name": "Injected"},
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["tenant_id"] == str(TENANT_A)

        from apps.patient_registry.models import Patient

        assert not Patient.objects.filter(
            tenant_id=TENANT_B, uhid="UH7777"
        ).exists()


class TestSearchScoping:
    def test_search_never_crosses_tenants(self, two_tenants, user):
        """The search action had a queryset-union bug that leaked.

        It combined two separately-filtered querysets with ``|``, which
        reintroduced the unfiltered base queryset.
        """
        response = _client_for(TENANT_A, user).get("/api/v1/patients/search/?q=UH0002")

        assert response.status_code == 200
        assert response.json() == []

    def test_search_finds_the_owning_tenant_match(self, two_tenants, user):
        response = _client_for(TENANT_A, user).get("/api/v1/patients/search/?q=UH0001")

        assert [row["uhid"] for row in response.json()] == ["UH0001"]


class TestUhidUniquenessIsPerTenant:
    def test_two_tenants_may_issue_the_same_uhid(self, two_tenants, user):
        """UHID is unique within a tenant, not globally.

        A global unique constraint would stop two hospitals from both issuing
        UH0001, which is exactly what happens in practice.
        """
        from apps.patient_registry.models import Patient

        # UH0001 already belongs to TENANT_A, so issuing it again under
        # TENANT_B is the case a global constraint would reject.
        Patient.objects.create(
            id=uuid.uuid4(),
            tenant_id=TENANT_B,
            uhid="UH0001",
            demographics={"name": "Same UHID, different tenant"},
        )

        assert Patient.objects.filter(uhid="UH0001").count() == 2
        assert (
            Patient.objects.filter(uhid="UH0001", tenant_id=TENANT_B).count() == 1
        )