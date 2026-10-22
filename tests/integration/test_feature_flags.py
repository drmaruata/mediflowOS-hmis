"""Per-tenant feature flags (PLT-006).

``platform.feature_flag`` was created by the app's ``0001`` and dropped by
``0005`` (``DeleteModel``), so this task re-adds it as ``0007`` and re-attaches
the row level security policy that ``0004`` had created and lost with the table.

The cases below are the ones that look like working code while being wrong:

* a flag that reports **on** when nothing has been configured - the whole point
  of ``flag_enabled`` is that it fails closed, and a helper that raises or
  guesses is worse than one that says no;
* a helper called from a Celery task or from view code, where no request has
  bound the tenant: on PostgreSQL an unbound query returns **nothing**, so the
  flag would read as off for every feature in the installation while the SQLite
  suite stayed green;
* a ``PUT`` that writes another hospital's row, or creates one under a forged
  ``tenant_id``;
* a table created with no policy, which answers every tenant's rows to any caller
  whose application-side filter is missing - and which ``makemigrations --check``
  cannot see, because RLS is DDL with no model state.

One limitation is stated rather than worked around: the PostgreSQL proof of the
policy (a non-owner role reading and writing across tenants) is environment-gated
on ``MEDIFLOW_TEST_PG*``, so what is pinned here is the *wiring* - that the
isolation suite discovers the table, that all three of its parametrized cases
cover it, and that ``0007`` re-enables the policy in the same migration that
creates the table.
"""
import uuid
from importlib import import_module
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, migrations, transaction
from rest_framework.test import APIClient

from apps.identity_tenancy.models import Role, Tenant, UserMembership
from apps.platform import services
from apps.platform.models import FeatureFlag
from apps.platform.services import flag_enabled
from apps.platform.views import FLAG_KEY_PATTERN

#: The gateway the isolation suite uses. Imported from that module rather than
#: reimplemented, so a change to how tables are discovered cannot leave this
#: assertion checking a stale rule.
from test_rls_isolation import _tenant_owned_tables

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT_A = uuid.UUID("a5f10000-0000-4000-8000-000000000001")
TENANT_B = uuid.UUID("b6f20000-0000-4000-8000-000000000002")

FLAGS_URL = "/api/v1/feature-flags/"

#: The migration under test, by the name ``makemigrations`` gave it.
MIGRATION_MODULE = "apps.platform.migrations.0007_featureflag"


def _make_client(tenant_id, username, slug, *, privileged):
    """An authenticated client of one tenant, plus its user.

    ``privileged`` sets ``Role.require_mfa``, the documented privileged-role
    marker (TEN-006) that the TEN-007 break-glass fan-out and the ABD-014 alert
    already filter on: ``Role`` has no ``is_admin`` column and its ``name`` is
    tenant-authored free text, so matching a name would miss every hospital that
    names its administrator role differently.
    """
    Tenant.objects.get_or_create(id=tenant_id, defaults={"name": slug, "slug": slug})
    user = get_user_model().objects.create_user(
        username=username, password="pw-for-feature-flags-only"
    )
    role = Role.objects.create(
        tenant_id=tenant_id,
        name=f"role-{slug}",
        permissions=[],
        require_mfa=privileged,
    )
    UserMembership.objects.create(user=user, tenant_id=tenant_id, role=role, active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_ID=str(tenant_id))
    return client, user


@pytest.fixture
def admin_a():
    """Tenant A as an administrator: the only caller allowed to write a flag."""
    return _make_client(TENANT_A, "flags-admin-a", "flags-admin-a", privileged=True)


@pytest.fixture
def plain_a():
    """Tenant A as an ordinary user: authenticated, but not privileged."""
    return _make_client(TENANT_A, "flags-plain-a", "flags-plain-a", privileged=False)


@pytest.fixture
def admin_b():
    """Tenant B as an administrator: the other hospital."""
    return _make_client(TENANT_B, "flags-admin-b", "flags-admin-b", privileged=True)


def _keys(response):
    """The keys in a paginated list body."""
    return [row["key"] for row in response.json()["results"]]


class TestFailsClosed:
    """``flag_enabled`` says "no" to everything it cannot affirm."""

    def test_an_unknown_key_is_off(self, admin_a):
        """Nothing has been configured, so the feature is off.

        The dangerous outcomes here are not only a missing row: a lookup that
        raises would take down whatever clinical path consulted it, and one that
        treats "not configured" as permission would switch a feature on for a
        hospital that never asked for it.
        """
        client, _ = admin_a
        assert client.get(FLAGS_URL).status_code == 200

        assert flag_enabled(TENANT_A, "never-configured") is False

    def test_a_row_written_without_enabled_is_off(self):
        """The column default, not only an explicit ``False``.

        Written through the ORM with no ``enabled`` argument, so the assertion is
        about the database default rather than about a value the API happened to
        send.
        """
        FeatureFlag.objects.create(tenant_id=TENANT_A, key="default-off")

        assert flag_enabled(TENANT_A, "default-off") is False

    def test_an_explicitly_disabled_row_is_off(self):
        FeatureFlag.objects.create(tenant_id=TENANT_A, key="explicit-off", enabled=False)

        assert flag_enabled(TENANT_A, "explicit-off") is False

    def test_a_flag_on_for_another_tenant_is_off_for_this_one(self):
        """Tenant A cannot see a flag only tenant B turned on.

        Not the isolation test - that is in the API class below - but a pin on the
        helper, because one that ignored the tenant argument would return True
        here and report one hospital's configuration to another.
        """
        FeatureFlag.objects.create(tenant_id=TENANT_B, key="b-only", enabled=True)

        assert flag_enabled(TENANT_A, "b-only") is False
        assert flag_enabled(TENANT_B, "b-only") is True

    def test_an_unknown_tenant_is_off(self):
        FeatureFlag.objects.create(tenant_id=TENANT_A, key="a-only", enabled=True)

        assert flag_enabled(uuid.uuid4(), "a-only") is False

    @pytest.mark.parametrize("tenant_id", ["", None, "not-a-uuid"])
    def test_an_unusable_tenant_argument_is_off_and_never_raises(self, tenant_id):
        """A caller that passes nonsense gets ``False``, not an exception.

        The helper is consulted from request paths, tasks and indicator code. An
        exception escaping it would turn a configuration lookup into a failed
        request on a clinical screen; ``False`` degrades to the feature being off,
        which is the state that tenant is in anyway.
        """
        assert flag_enabled(tenant_id, "a-only") is False

    def test_a_database_failure_is_off_and_never_raises(self, monkeypatch):
        """Even an unusable database answers ``False``.

        Propagating ``DatabaseError`` is what would turn a database blip into a
        failed request on whatever screen consulted the flag. The failure is
        logged by tenant and key; a flag name is configuration, not patient data,
        so both are safe to log - and ``exc_info`` is omitted for the reason
        ``apps.platform.views`` omits it, so an error whose message quotes the
        bad value cannot put that value into the log aggregation.
        """
        class _Exploding:
            class objects:
                @staticmethod
                def filter(**kwargs):
                    raise DatabaseError("simulated connection failure")

        monkeypatch.setattr(services, "FeatureFlag", _Exploding)

        assert flag_enabled(TENANT_A, "a-only") is False


class TestTenantBinding:
    """The helper binds the tenant itself, because its caller may not have.

    ``platform.feature_flag`` is RLS-protected and the policy reads
    ``app.tenant_id`` - a *transaction-scoped* session setting
    (``common/tenant.py``). A query issued with no binding therefore returns zero
    rows on PostgreSQL rather than raising, so a helper that relied on its caller
    to bind would report every feature off in production and pass every SQLite
    test. That is the coupling pinned below.

    What cannot be pinned here, and is not claimed: the PostgreSQL observation
    itself. The suite runs on in-memory SQLite, where ``bind_tenant_session`` is a
    no-op, so what is asserted is that the helper calls it - with the tenant, and
    from inside a transaction. The end-to-end proof is the isolation gate's,
    which is gated on ``MEDIFLOW_TEST_PG*``.
    """

    def test_the_helper_binds_the_tenant_inside_a_transaction(self, monkeypatch):
        """Called with no pre-bound tenant, and the value is still right.

        The spy records ``in_atomic_block`` as well as the argument, because the
        argument alone is not the requirement: ``set_config(...,
        is_local=true)`` issued outside a transaction is silently discarded, and
        the result would be a helper that appears to bind and does not.
        """
        FeatureFlag.objects.create(tenant_id=TENANT_A, key="bound-here", enabled=True)
        calls = []
        real_bind = services.bind_tenant_session

        def spy(tenant_id, facility_id=None):
            calls.append((str(tenant_id), transaction.get_connection().in_atomic_block))
            return real_bind(tenant_id, facility_id)

        monkeypatch.setattr(services, "bind_tenant_session", spy)

        assert flag_enabled(TENANT_A, "bound-here") is True

        assert calls == [(str(TENANT_A), True)]

    def test_the_helper_is_safe_inside_an_existing_transaction(self):
        """A caller that already opened one - a view, under ``ATOMIC_REQUESTS``.

        The nested ``atomic()`` is a savepoint, and the read has to happen inside
        it: the setting it binds is transaction-scoped, so a read issued before
        the block would be evaluated against whatever the caller's transaction
        already had. This is the shape every in-request caller has. It asks about
        the *caller's own* tenant - the rebind a different tenant's question
        would cause is the next test's subject.
        """
        FeatureFlag.objects.create(tenant_id=TENANT_A, key="nested", enabled=True)

        with transaction.atomic():
            assert flag_enabled(TENANT_A, "nested") is True

    def test_a_nested_call_rebinds_the_enclosing_transaction_to_its_own_tenant(
        self, monkeypatch
    ):
        """Pinned as a *decision*, because SQLite cannot show the effect.

        ``flag_enabled``'s docstring tells a caller that asking about another
        tenant from inside its own transaction leaves that transaction bound to
        the other tenant for the rest of its life, and that this is a contract
        rather than a guard. Neither half is observable on in-memory SQLite:
        ``bind_tenant_session`` is a no-op there, so there is no setting and
        nothing to rebind, and the PostgreSQL effect is what
        ``tests/integration/test_rls_isolation.py`` proves against a real
        server.

        What *is* observable - and what a later change to the helper would
        break - is the decision behind the contract: it binds the tenant it was
        given, unconditionally, including when the enclosing transaction has
        already bound a different one. Refusing instead ("already bound to
        someone else, so answer ``False``") would drop the second call and fail
        here; so would skipping the bind to avoid the rebind, which is the exact
        branch the ``atomic()`` exists to remove.
        """
        FeatureFlag.objects.create(tenant_id=TENANT_B, key="partner", enabled=True)
        calls = []
        real_bind = services.bind_tenant_session

        def spy(tenant_id, facility_id=None):
            calls.append(str(tenant_id))
            return real_bind(tenant_id, facility_id)

        monkeypatch.setattr(services, "bind_tenant_session", spy)

        # The shape the contract is about: one transaction, already bound to
        # this caller's tenant, asking about somebody else's.
        with transaction.atomic():
            services.bind_tenant_session(str(TENANT_A))
            # The question is answered honestly - a flag that is genuinely on for
            # TENANT_B reads on. The cost is the rebind above, not a wrong answer.
            assert flag_enabled(TENANT_B, "partner") is True

        assert calls == [str(TENANT_A), str(TENANT_B)]


class TestToggling:
    """``PUT`` is the whole write surface, and it is an upsert."""

    def test_a_write_turns_the_flag_on_and_the_helper_agrees(self, admin_a):
        client, _ = admin_a

        response = client.put(
            f"{FLAGS_URL}abdm-linkage/", {"enabled": True, "description": "ABDM linking"}
        )

        assert response.status_code == 200, response.content
        assert response.json()["enabled"] is True
        assert response.json()["key"] == "abdm-linkage"
        # The row and the helper agree, which is the point of the pair: a flag
        # the interface can toggle but the backend cannot read is worse than no
        # flag at all, because it looks configured.
        assert FeatureFlag.objects.get(key="abdm-linkage").tenant_id == TENANT_A
        assert flag_enabled(TENANT_A, "abdm-linkage") is True

    def test_the_flag_appears_in_the_tenant_list_after_the_write(self, admin_a):
        client, _ = admin_a
        client.put(f"{FLAGS_URL}lab-automation/", {"enabled": True})

        response = client.get(FLAGS_URL)

        assert response.status_code == 200
        assert "lab-automation" in _keys(response)

    def test_a_second_write_turns_it_off_again(self, admin_a):
        client, _ = admin_a
        client.put(f"{FLAGS_URL}toggle/", {"enabled": True})

        response = client.put(f"{FLAGS_URL}toggle/", {"enabled": False})

        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert flag_enabled(TENANT_A, "toggle") is False

    def test_a_put_for_a_key_with_no_row_creates_it(self, admin_a):
        """PUT upserts, because nothing else on this viewset creates a flag.

        ``http_method_names`` excludes POST, so there is no plain create route;
        without the upsert the interface would have no way to turn a feature on
        for the first time. The status is 200 whether or not the row existed, so
        the same request twice answers the same way - which is what PUT promises.
        """
        client, _ = admin_a
        assert not FeatureFlag.objects.exists()

        response = client.put(f"{FLAGS_URL}fresh/", {"enabled": True})

        assert response.status_code == 200, response.content
        row = FeatureFlag.objects.get()
        assert (row.key, row.tenant_id, row.enabled) == ("fresh", TENANT_A, True)

    def test_a_description_is_optional_and_defaults_to_empty(self, admin_a):
        """``description`` is metadata, so a flag without one is not an error.

        It is ``NOT NULL`` with an empty-string default rather than nullable: two
        spellings of "no description" would have to be handled everywhere the row
        is rendered, and ``NULL`` is not a state a human sets deliberately.
        """
        client, _ = admin_a

        response = client.put(f"{FLAGS_URL}terse/", {"enabled": True})

        assert response.status_code == 200, response.content
        assert response.json()["description"] == ""
        assert FeatureFlag.objects.get(key="terse").description == ""

    @pytest.mark.parametrize(
        "key",
        ["has space", "has/slash", "quote'd", "", "a" * 65],
        ids=["space", "slash", "quote", "empty", "too-long"],
    )
    def test_an_unusable_key_in_the_url_is_refused(self, admin_a, key):
        """A key arriving in the URL is stored, so it is validated.

        This endpoint writes whatever the path segment spells - the one write on
        it that no client-side validation reaches - and a key becomes part of a
        feature-gate name in code as well as part of a URL. A key the column would
        silently truncate, or that could not be written as an identifier, is
        refused rather than stored. Some of these never reach the view at all
        (a slash or an empty segment does not match the router's URL pattern),
        which is why both refusals are accepted: the outcome that matters is that
        no row is written.
        """
        client, _ = admin_a

        response = client.put(f"{FLAGS_URL}{key}/", {"enabled": True})

        assert response.status_code in (400, 404), response.content
        assert not FeatureFlag.objects.exists()

    @pytest.mark.parametrize(
        "key",
        ["a", "0", "abdm-linkage", "lab_automation", "v2_x-0", "a" * 64],
        ids=["one", "digit", "hyphen", "underscore", "mixed", "max-length"],
    )
    def test_every_advertised_key_shape_is_routable(self, admin_a, key):
        """The charset the module documents is the charset the router delivers.

        ``FLAG_KEY_PATTERN`` used to advertise ``.``, which
        ``SimpleRouter._default_value_pattern`` (``[^/.]+``) cannot match - so a
        dotted key 404ed at the URL pattern and never reached the validation
        that claimed to accept it. The two sets are now pinned against each
        other in the running system rather than against the router's constant,
        because the constant is the thing that could change: every character the
        pattern claims is put through a real URL and has to reach the row.

        The upper bound is included deliberately - a 64-character key is the
        column's own limit, so a pattern that were tightened below it would be
        advertised as accepted and then refused.
        """
        client, _ = admin_a

        response = client.put(f"{FLAGS_URL}{key}/", {"enabled": True})

        assert response.status_code == 200, response.content
        assert FeatureFlag.objects.get().key == key

    def test_a_dotted_key_is_neither_routable_nor_advertised(self, admin_a):
        """The other direction: what the router drops is not in the charset.

        Pinned as a pair with the case above. ``.`` is the one character whose
        absence from the pattern is a decision rather than an accident - a dotted
        key is a reasonable thing to want (``abdm.linkage``) and it is refused
        because the router cannot route it, so the refusal has to be visible in
        both places at once: a 404 at the URL pattern, and no claim anywhere
        that it would have been accepted.
        """
        client, _ = admin_a

        response = client.put(f"{FLAGS_URL}abdm.linkage/", {"enabled": True})

        assert response.status_code == 404, response.content
        assert FLAG_KEY_PATTERN.fullmatch("abdm.linkage") is None
        assert not FeatureFlag.objects.exists()

    def test_a_patch_changes_only_what_it_names(self, admin_a):
        """PATCH is the same upsert with a partial body.

        Asserted both ways round: on an existing row the unnamed field keeps its
        value, and on a key with no row the flag is created - a PATCH that
        404'd would leave the caller unable to set one field of a flag that does
        not exist yet.
        """
        client, _ = admin_a
        client.put(
            f"{FLAGS_URL}partial/", {"enabled": True, "description": "kept as-is"}
        )

        response = client.patch(f"{FLAGS_URL}partial/", {"description": "changed"})

        assert response.status_code == 200, response.content
        row = FeatureFlag.objects.get(key="partial")
        assert row.description == "changed"
        assert row.enabled is True

        assert client.patch(f"{FLAGS_URL}brand-new/", {"enabled": True}).status_code == 200
        assert flag_enabled(TENANT_A, "brand-new") is True

    @pytest.mark.parametrize("method", ["post", "delete"])
    def test_there_is_no_create_or_delete_route(self, admin_a, method):
        """A flag is set, not created or deleted by a second contract.

        POST is excluded because the upsert in ``PUT`` is the create path, and two
        would be two contracts to keep in step. DELETE would remove the row that
        records a decision: the helper would still answer (off, by absence), but
        the decision would have vanished from the configuration and from the audit
        trail's view of it, which is a silent deactivation with no event.
        """
        client, _ = admin_a

        response = getattr(client, method)(
            FLAGS_URL, {"key": "route-check", "enabled": True}
        )

        assert response.status_code == 405, response.content
        assert not FeatureFlag.objects.exists()


class TestTenantIsolation:
    """One hospital's flags are neither visible to nor writable by another."""

    def test_a_list_holds_only_the_requesting_tenants_rows(self, admin_a, admin_b):
        client_a, _ = admin_a
        FeatureFlag.objects.create(tenant_id=TENANT_B, key="b-secret", enabled=True)
        FeatureFlag.objects.create(tenant_id=TENANT_A, key="a-own", enabled=True)

        response = client_a.get(FLAGS_URL)

        assert response.status_code == 200
        assert _keys(response) == ["a-own"]
        assert "b-secret" not in str(response.content)
        assert str(TENANT_B) not in str(response.content)

    def test_the_same_key_exists_independently_for_each_tenant(self, admin_a, admin_b):
        """Uniqueness is ``(tenant_id, key)``, so a key is per hospital.

        That pair is what makes the flag a per-tenant decision rather than a
        global one: two hospitals rolling the same feature out at different times
        is the ordinary case, not a conflict.
        """
        client_a, _ = admin_a
        client_b, _ = admin_b
        assert client_a.put(f"{FLAGS_URL}shared/", {"enabled": True}).status_code == 200
        assert client_b.put(f"{FLAGS_URL}shared/", {"enabled": False}).status_code == 200

        assert FeatureFlag.objects.filter(key="shared").count() == 2
        assert flag_enabled(TENANT_A, "shared") is True
        assert flag_enabled(TENANT_B, "shared") is False
        assert _keys(client_a.get(FLAGS_URL)) == ["shared"]
        assert client_b.get(f"{FLAGS_URL}shared/").json()["enabled"] is False

    def test_a_write_cannot_flip_another_tenants_flag(self, admin_a):
        """Tenant A writing B's key leaves B's row exactly as it was.

        The upsert makes this the sharpest form of the test: A's PUT for B's key
        has somewhere to go - it creates A's own row - so a view that looked the
        flag up without the tenant filter would overwrite B's value and still
        answer 200.
        """
        client_a, _ = admin_a
        b_row = FeatureFlag.objects.create(
            tenant_id=TENANT_B, key="b-decision", enabled=True
        )

        response = client_a.put(f"{FLAGS_URL}b-decision/", {"enabled": False})

        assert response.status_code == 200, response.content
        b_row.refresh_from_db()
        assert b_row.enabled is True
        assert flag_enabled(TENANT_B, "b-decision") is True
        # A's own row exists, under A's tenant - not B's.
        assert FeatureFlag.objects.filter(key="b-decision", tenant_id=TENANT_A).exists()
        assert flag_enabled(TENANT_A, "b-decision") is False

    def test_the_tenant_and_key_in_the_body_are_ignored(self, admin_a):
        """Only the URL's key and the request's tenant decide the row.

        ``tenant_id`` and ``key`` are read-only in the serializer. A writable
        ``tenant_id`` would let a caller write another hospital's configuration,
        and on a create would ask to write a row *claiming* to belong to another
        tenant - which the RLS ``WITH CHECK`` clause would reject, but which the
        API should never ask the database to judge.
        """
        client, _ = admin_a

        response = client.put(
            f"{FLAGS_URL}from-url/",
            {
                "enabled": True,
                "tenant_id": str(TENANT_B),
                "key": "forged",
                "description": "forged description",
            },
        )

        assert response.status_code == 200, response.content
        row = FeatureFlag.objects.get()
        assert row.key == "from-url"
        assert row.tenant_id == TENANT_A
        # The one free-text field is the one that was supplied.
        assert row.description == "forged description"


class TestWriteAuthorization:
    """Writing a flag is administrator-only; reading it is not.

    The predicate is ``Role.require_mfa`` (TEN-006), read from the database
    rather than from the token's claims, so a stale or hand-minted token cannot
    grant it and a revoked membership stops granting it at once. It is the same
    marker the TEN-007 break-glass fan-out and the ABD-014 alert already filter
    on: this is a third use of one predicate, not a second definition of
    "administrator".
    """

    def test_a_privileged_user_can_write(self, admin_a):
        client, _ = admin_a

        response = client.put(f"{FLAGS_URL}privileged/", {"enabled": True})

        assert response.status_code == 200, response.content

    def test_an_ordinary_user_cannot_write(self, plain_a):
        client, _ = plain_a

        response = client.put(f"{FLAGS_URL}not-yours/", {"enabled": True})

        assert response.status_code == 403, response.content
        assert not FeatureFlag.objects.exists()

    def test_an_inactive_membership_cannot_write(self, admin_a):
        """Active is part of the predicate: a revoked membership is not authority.

        Left in the database rather than deleted - the same shape a tenant
        offboarding takes - so the row is still there and still names the role.
        """
        client, user = admin_a
        membership = UserMembership.objects.get(user=user)
        membership.active = False
        membership.save(update_fields=["active"])

        response = client.put(f"{FLAGS_URL}revoked/", {"enabled": True})

        assert response.status_code == 403, response.content
        assert not FeatureFlag.objects.exists()

    def test_administrating_another_tenant_grants_nothing_here(self, plain_a, admin_b):
        """Privilege is per tenant.

        One account that is an administrator of B and an ordinary member of A can
        write in B and not in A. The gate filters the membership on the request's
        tenant as well as on the role, so authority does not travel with the
        person - the horizontal case, which the vertical case above does not
        reach.
        """
        client_a, user_a = plain_a
        UserMembership.objects.create(
            user=user_a,
            tenant_id=TENANT_B,
            role=Role.objects.get(tenant_id=TENANT_B),
            active=True,
        )

        response = client_a.put(f"{FLAGS_URL}cross-tenant/", {"enabled": True})

        assert response.status_code == 403, response.content
        assert not FeatureFlag.objects.exists()

    def test_an_ordinary_user_can_read(self, plain_a):
        """Reads stay open to any authenticated member of the tenant.

        A flag is configuration the client needs to render the right screens, so
        gating the list behind administrator rights would hide it from exactly
        the users who must not act on it. The tenant filter is the control here.
        """
        client, _ = plain_a
        FeatureFlag.objects.create(tenant_id=TENANT_A, key="visible", enabled=True)

        response = client.get(FLAGS_URL)

        assert response.status_code == 200
        assert _keys(response) == ["visible"]

    @pytest.mark.parametrize("method", ["get", "put"])
    def test_an_anonymous_caller_is_refused(self, method):
        """No credential, no access - and 401 rather than 403.

        ``IsAuthenticated`` runs before the privileged gate, so an anonymous
        caller is told it needs to authenticate rather than being told it is not
        an administrator it never claimed to be.
        """
        client = APIClient()
        client.credentials(HTTP_X_TENANT_ID=str(TENANT_A))

        response = getattr(client, method)(
            f"{FLAGS_URL}anonymous/", {"enabled": True}
        )

        assert response.status_code == 401, response.content

    def test_a_write_with_no_tenant_resolved_is_refused(self, admin_a):
        """No tenant in the request, no membership to find, no write.

        The gate returns ``False`` on a missing tenant rather than raising, and
        that is what makes this fail closed: there is no user whose authority
        could be evaluated against an unknown tenant, so nothing is written.
        """
        client, _ = admin_a
        client.credentials()

        response = client.put(f"{FLAGS_URL}no-tenant/", {"enabled": True})

        assert response.status_code == 403, response.content
        assert not FeatureFlag.objects.exists()


class TestRowLevelSecurityWiring:
    """The table must be under the isolation gate, and the policy must exist.

    ``0004`` created the policy and ``0005``'s ``DeleteModel`` dropped the table
    with it, so a bare ``CreateModel`` here would leave a policy-less
    ``platform.feature_flag`` on PostgreSQL while the registry still claimed
    ``0004`` covered it - a silent cross-tenant hole of exactly the class the
    registry exists to catch. Nothing about that is visible to
    ``makemigrations --check``.
    """

    def test_the_isolation_gate_discovers_the_table(self):
        assert "platform.feature_flag" in _tenant_owned_tables()

    def test_every_parametrized_isolation_case_covers_the_table(self):
        """Three cases per table, and the new table is in all three.

        The gate walks the model registry by ``tenant_id`` column, so the table is
        covered without anyone listing it. Asserted per case because "the table is
        discovered" and "the cases that use it include this table" are different
        claims, and only the second is what makes the read, the write and the
        fail-closed gates cover it.
        """
        suite = import_module("test_rls_isolation")
        cases = [
            suite.TestCrossTenantReadsFail.test_tenant_a_cannot_see_tenant_b_rows,
            suite.TestCrossTenantWritesFail.test_tenant_a_cannot_write_into_tenant_b,
            suite.TestFailsClosedWithoutContext.test_no_tenant_context_sees_nothing,
        ]

        assert len(cases) == 3
        for case in cases:
            marks = [mark for mark in case.pytestmark if mark.name == "parametrize"]
            assert len(marks) == 1, case
            assert "table" in marks[0].args
            assert "platform.feature_flag" in marks[0].args[1], case

    def test_the_migration_creates_the_table_and_re_enables_the_policy(self):
        """The table and the policy are attached in one migration, in that order.

        Two structural claims and not one textual one. Deleting
        ``migrations.RunPython(forwards, backwards)`` from ``0007``'s
        ``operations`` leaves ``rls.enable``, ``rls.disable`` and
        ``is_postgres`` all still reading in the file - ``forwards`` and
        ``backwards`` are still defined, just referenced by nothing - so a check
        that only greps the source passes on a migration that attaches no policy
        at all, and says nothing about order, which is the half that actually
        matters: the policy has to land on a table that exists, or the
        ``RunPython`` raises on PostgreSQL and no-ops on the SQLite the fast
        suite runs on.

        So the operations are compared as *operations*: exactly one
        ``CreateModel`` for ``FeatureFlag``, exactly one ``RunPython``, the
        ``RunPython``'s code and reverse-code the module's own ``forwards`` and
        ``backwards`` (so the operation that runs is provably the one holding
        ``rls.enable``, not an unrelated one), and the ``RunPython`` *after* the
        ``CreateModel``. The substring assertions are kept as a floor on the
        bodies of those two functions - they are what a future refactor of
        ``forwards`` has to keep.
        """
        migration = import_module(MIGRATION_MODULE)
        operations = migration.Migration.operations
        source = Path(migration.__file__).read_text(encoding="utf-8")

        assert migration.TABLES == ("platform.feature_flag",)
        # The table is created *by this migration* - not by a re-run of 0001,
        # which would be a rewrite of applied history.
        created = [
            index
            for index, operation in enumerate(operations)
            if isinstance(operation, migrations.CreateModel)
            and operation.name == "FeatureFlag"
        ]
        assert len(created) == 1, operations
        attached = [
            index
            for index, operation in enumerate(operations)
            if isinstance(operation, migrations.RunPython)
        ]
        assert len(attached) == 1, operations
        # ...and the policy is attached in the same migration, *after* the table
        # exists, because the one 0004 applied no longer exists. The comparison is
        # on indices rather than on membership, so an inversion is a failure
        # rather than a silently reordered file.
        assert attached[0] > created[0], operations
        run_python = operations[attached[0]]
        assert run_python.code is migration.forwards
        assert run_python.reverse_code is migration.backwards
        # The bodies those two names point at are what the indices above cannot
        # see, so they are still pinned - as the floor they are, not as the
        # evidence.
        assert "rls.enable(TABLES" in source
        assert "rls.disable(TABLES" in source
        assert "is_postgres" in source

    def test_the_migration_does_not_repeat_the_applied_history(self):
        """0001-0006 are immutable; the re-add is 0007 and depends on 0006.

        Asserted because the tempting alternatives - editing ``0004`` to
        re-enable the policy, or restoring the model in ``0001`` - produce two
        databases with different histories and no report of the divergence.
        """
        migration = import_module(MIGRATION_MODULE)
        dependencies = list(migration.Migration.dependencies)

        assert len(dependencies) == 1
        assert dependencies[0] == ("platform", "0006_enable_row_level_security")

    def test_the_registry_records_the_re_enabled_table(self):
        """Both registries name it now, and the registry says why.

        ``platform.feature_flag`` is in ``PLAN`` because ``0004`` - applied and
        immutable - names it, and in ``STANDALONE`` because ``0007`` re-enables
        the policy the dropped table took with it. That overlap is legitimate, and
        it is what ``reapplies`` records: the disjointness rule is now "every
        overlap is a recorded re-application, and every recorded re-application
        names a table a PLAN entry wrote and a later migration than it", which is
        a claim that can still be falsified - where "the two sets are disjoint"
        would have been a rule this table cannot satisfy.
        """
        script = import_module("scripts.add_rls_migrations")
        entry = next(
            e for e in script.STANDALONE["platform"] if e.tables == ("platform.feature_flag",)
        )

        assert entry.filename == "0007_featureflag.py"
        assert entry.previous == "0006_enable_row_level_security"
        assert entry.reapplies == ("platform.feature_flag",)
        assert "platform.feature_flag" in script.PLAN["platform"][0]
        assert import_module(f"apps.platform.migrations.{entry.filename[:-3]}").TABLES == (
            entry.tables
        )
        assert script.verify_standalone() == ()
        assert script.verify_reapplied() == ()

    def test_the_table_is_not_recorded_as_deliberately_unprotected(self):
        script = import_module("scripts.add_rls_migrations")

        assert "platform.feature_flag" not in script.UNPROTECTED_TABLES
