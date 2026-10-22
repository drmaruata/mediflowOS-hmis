"""REST boards vs. Channels sockets: the split is pinned, not assumed (PLT-003, PLT-008, INT-013).

Architecture doc section 13 approves **two** WebSocket consumers — notification
delivery and live vitals — and requires every other operational screen to poll
over REST. That split is a security and architecture boundary, not a
preference: a socket's tenant is bound once, at handshake time, from a signed
claim, while a REST board is scoped per request from the same claim; a board
that quietly opened a socket would inherit the *socket* scoping rules and the
polling cadence nobody designed for.

Each pin below names the failure it would catch:

``TestOperationalBoardsAreRest``
    A board that reaches for the channel layer, reaches a consumer, or routes
    somewhere other than a DRF action. The channel layer is replaced with a
    guard that raises, so a 200 proves the request never touched Channels —
    and the guard is asserted to be *armed* first, because a 200 under a patch
    that missed its call site is the vacuous pass this test exists to rule out.

``TestWebSocketRouteSet``
    The exact route set, both in ``apps.realtime.routing`` and in the router
    ``config/asgi.py`` actually serves, with the consumer class pinned behind
    each path. Asserted as a set, so a third consumer fails here rather than
    widening the surface, and a route swapped onto the wrong consumer fails
    too. It agrees with the Task 22 handshake suite rather than restating it:
    that suite proves *who* may connect, this one proves *what exists*.

``TestBoardTenantScoping``
    Horizontal isolation of all three boards. A viewset whose queryset was
    dropped from ``TenantScopedQuerysetMixin`` still answers 200 — with another
    hospital's rows — so the assertion is on the returned identifiers, not on
    the status code, and the foreign row's id is checked absent from the raw
    body as well.

``TestEmergencyTrackingBoardFilters``
    The emergency board's query-parameter contract, including the ``FieldError``
    that made ``?status=`` a 500. ``Triage`` has no ``status`` column; the
    filter now names ``category``, which is the column that exists.

What is **not** claimed: none of this exercises PostgreSQL. Row level security
is what actually enforces isolation in production, and its cross-tenant proof
stays behind the ``MEDIFLOW_TEST_PG*`` gate in ``test_rls_isolation.py``. What
is pinned here is the application-side half — the transport split, and the
queryset scoping that a missing RLS policy would otherwise expose.
"""
import ast
import uuid
from pathlib import Path

import pytest
from asgiref.sync import async_to_sync
from channels import consumer as channels_consumer
from channels import layers as channels_layers
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.asgi import ASGIHandler
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.emergency import views as emergency_views
from apps.emergency.models import Triage
from apps.identity_tenancy.models import Role, Tenant, UserMembership
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.ipd import views as ipd_views
from apps.ipd.models import BedStatus
from apps.opd import views as opd_views
from apps.opd.models import Token
from apps.platform import views as platform_views
from apps.realtime.consumers import NotificationConsumer, VitalsConsumer
from apps.realtime.routing import websocket_urlpatterns
from config.asgi import application as asgi_application

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT_A = uuid.UUID("c7a30000-0000-4000-8000-00000000000a")
TENANT_B = uuid.UUID("d8b40000-0000-4000-8000-00000000000b")

QUEUE_URL = "/api/v1/tokens/queue/"
#: The bed board is registered twice — once as an explicit top-level path and
#: once as the router's detail=False action. Both are pinned, because both are
#: live and a client holding either must get the same tenant-scoped board.
BED_BOARD_URLS = ("/api/v1/bed-status/board/", "/api/v1/board/")
#: The emergency board, likewise. Note the asymmetry the router produces: the
#: action's *url_name* is ``tracking-board`` (hyphenated) while its *url_path* is
#: ``tracking_board`` (underscored), so ``/api/v1/triages/tracking-board/`` is
#: the detail route with a non-UUID pk and answers 404. The two routable forms
#: are pinned below and the hyphen is pinned as the detail route it is.
TRACKING_BOARD_URLS = ("/api/v1/triages/tracking_board/", "/api/v1/tracking-board/")

#: name -> (viewset, action, every URL that reaches it)
BOARDS = {
    "opd-token-queue": (opd_views.TokenViewSet, "queue", (QUEUE_URL,)),
    "ipd-bed-board": (ipd_views.BedStatusViewSet, "board", BED_BOARD_URLS),
    "emergency-tracking-board": (
        emergency_views.TriageViewSet,
        "tracking_board",
        TRACKING_BOARD_URLS,
    ),
}

#: INT-012 approves these two and no others. Written without the regex anchors
#: ``re_path`` adds, because the anchor is ``re_path``'s business; what is
#: pinned is the path each route answers.
APPROVED_WEBSOCKET_ROUTES = {"ws/notifications/", "ws/vitals/"}

#: The consumer each approved route is expected to serve. A route reachable but
#: wired to the wrong consumer would pass a set-only assertion.
EXPECTED_CONSUMER_FOR = {
    "ws/notifications/": NotificationConsumer,
    "ws/vitals/": VitalsConsumer,
}

#: Paths a board *could* plausibly have been given a socket instead of REST.
#: Every one of them must match no route in the ASGI-wired router.
BOARD_WEBSOCKET_CANDIDATES = (
    "ws/tokens/queue/",
    "ws/opd/queue/",
    "ws/bed-status/board/",
    "ws/board/",
    "ws/ipd/board/",
    "ws/triages/tracking-board/",
    "ws/tracking-board/",
    "ws/emergency/tracking-board/",
    "ws/triage/",
    "ws/beds/",
)

BOARD_VIEW_MODULES = (opd_views, ipd_views, emergency_views)


class ChannelsReachedDuringABoard(Exception):
    """Raised by the guard installed by :func:`no_channels`."""


def _refuse_channel_layer(*args, **kwargs):
    """Stand-in for every entry point into Channels."""
    raise ChannelsReachedDuringABoard(
        "an operational board reached for Channels; the split is REST-only (PLT-003)"
    )


@pytest.fixture
def no_channels(monkeypatch):
    """Make every route into Channels fail loudly, and prove the guard is live.

    Three seams are closed, because a board could reach Channels through any of
    them and closing one is not evidence about the others:

    * ``channels.layers.get_channel_layer`` — what view code that wants to push
      an event calls, and what ``apps.platform.views`` holds a module-level
      reference to (hence that module is patched by name too, since rebinding
      ``channels.layers`` would not reach an already-bound name);
    * ``channels.consumer.get_channel_layer`` — the *same function object*, but
      re-imported into ``channels.consumer``'s namespace, which is the one every
      consumer calls from ``AsyncConsumer.__call__``;
    * both consumers' ``connect`` entry points, so a socket opened during a
      board request fails even if the layer lookup had somehow been bypassed.

    The closing assertion is the point of the fixture: without it a 200 could
    mean "the board never reached for Channels" or "the patch missed the call
    site", and only one of those is the property being pinned.
    """
    monkeypatch.setattr(channels_layers, "get_channel_layer", _refuse_channel_layer)
    monkeypatch.setattr(channels_consumer, "get_channel_layer", _refuse_channel_layer)
    monkeypatch.setattr(platform_views, "get_channel_layer", _refuse_channel_layer)
    for consumer_class in (NotificationConsumer, VitalsConsumer):
        monkeypatch.setattr(consumer_class, "connect", _refuse_channel_layer)

    with pytest.raises(ChannelsReachedDuringABoard):
        channels_layers.get_channel_layer()
    with pytest.raises(ChannelsReachedDuringABoard):
        NotificationConsumer.connect(object())
    with pytest.raises(ChannelsReachedDuringABoard):
        VitalsConsumer.connect(object())

    return _refuse_channel_layer


def _tenant_client(slug, username, tenant_id):
    """A tenant and an authenticated client bound to it by a *signed* token.

    The tenant comes from ``TenantAwareTokenSerializer``'s claim, which
    :class:`common.authentication.TenantBoundJWTAuthentication` reads inside the
    view, so these clients travel the production path. ``force_authenticate``
    plus an ``X-Tenant-Id`` header would have been shorter, but it would leave
    the scoping under test resting on a header a caller can edit — which is the
    one mechanism this codebase removed.

    The tenant id is passed in rather than minted here so the seeded board rows
    and the client's own signed claim are provably the same tenant.
    """
    tenant = Tenant.objects.create(id=tenant_id, name=slug, slug=slug)
    user = get_user_model().objects.create_user(
        username=username, password="transport-split-test-only"
    )
    role = Role.objects.create(tenant=tenant, name=f"role-{slug}", permissions=[])
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    access = str(TenantAwareTokenSerializer.get_token(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return {"client": client, "tenant": tenant, "user": user, "access": access}


@pytest.fixture
def context_a():
    return _tenant_client("board-alpha", "board-alpha-user", TENANT_A)


@pytest.fixture
def context_b():
    return _tenant_client("board-beta", "board-beta-user", TENANT_B)


@pytest.fixture
def client_a(context_a):
    return context_a["client"]


@pytest.fixture
def client_b(context_b):
    return context_b["client"]


def _rows_for(tenant_id):
    """Seed one waiting and one called token, two beds and three triages.

    The called token is the reason the queue pin can be sharp: a queue that
    ignored its ``status="waiting"`` filter would answer 200 with four rows
    instead of two, and only a check on identifiers catches that.
    """
    waiting = Token.objects.create(
        tenant_id=tenant_id,
        patient_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        series="A",
        number=1,
        status="waiting",
    )
    called = Token.objects.create(
        tenant_id=tenant_id,
        patient_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        series="A",
        number=2,
        status="called",
    )
    beds = [
        BedStatus.objects.create(
            tenant_id=tenant_id, bed_id=uuid.uuid4(), ward_id=uuid.uuid4(), occupied=True
        ),
        BedStatus.objects.create(
            tenant_id=tenant_id, bed_id=uuid.uuid4(), ward_id=uuid.uuid4(), occupied=False
        ),
    ]
    triages = [
        Triage.objects.create(tenant_id=tenant_id, patient_id=uuid.uuid4(), category=category)
        for category in ("I", "III", "V")
    ]
    return {
        # Stringified, because the comparison below is against a JSON body and
        # ``assert {uuid} == {"uuid"}`` is a difference, not an equality.
        "queue": [str(waiting.id)],
        "board": [str(row.id) for row in beds],
        "tracking_board": [str(row.id) for row in triages],
        "not_in_queue": [str(called.id)],
    }


def _route_path(route):
    """A websocket URLPattern's path, minus the anchor ``re_path`` added."""
    return route.pattern.regex.pattern.removesuffix("$")


def _asgi_websocket_router():
    """The ``URLRouter`` ``config/asgi.py`` actually serves sockets through.

    ``config.asgi.py`` composes the application as
    ``token_auth_middleware(URLRouter(websocket_urlpatterns))``, so the router
    is one closure cell deep inside the middleware rather than an attribute
    anybody can read. Walking the closure is what makes this pin about the
    *served* routing table rather than about the module someone expects to be
    the one in use — a second list declared inline in ``asgi.py`` would satisfy
    every other assertion in this file and route somewhere else entirely.
    """
    assert isinstance(asgi_application, ProtocolTypeRouter), type(asgi_application)
    websocket_app = asgi_application.application_mapping["websocket"]
    routers = [
        cell.cell_contents
        for cell in (getattr(websocket_app, "__closure__", None) or ())
        if isinstance(cell.cell_contents, URLRouter)
    ]
    assert len(routers) == 1, (
        "config/asgi.py must route sockets through exactly one URLRouter; "
        f"found {len(routers)}"
    )
    return routers[0]


def _asgi_routes_matching(path):
    """Routes in the served websocket router that match ``path``.

    Matching through the router's own ``routes`` rather than by reading
    ``websocket_urlpatterns`` means the answer comes from the table ASGI
    dispatches on, so a route the router would never reach cannot be counted as
    covering a path.
    """
    relative = path.lstrip("/")
    return [route for route in _asgi_websocket_router().routes if route.pattern.match(relative)]


def _run(scenario):
    """Drive one coroutine to completion from a sync test.

    pytest-asyncio is not a dependency of this project (see
    ``test_realtime_consumers``, which documents why), so the communicator is
    driven with ``async_to_sync`` and the whole interaction lives in a single
    coroutine: each call would otherwise get a fresh event loop in a fresh
    thread, and the consumer's task would never see the frames.
    """
    return async_to_sync(scenario)()


async def _handshake(path, token):
    communicator = WebsocketCommunicator(asgi_application, f"{path}?token={token}")
    connected, _ = await communicator.connect()
    await communicator.disconnect()
    return connected


class TestOperationalBoardsAreRest:
    """The three boards answer over HTTP and never touch Channels (PLT-003)."""

    @pytest.mark.parametrize("board", sorted(BOARDS))
    def test_the_board_answers_json_with_no_websocket_involvement(
        self, board, client_a, no_channels
    ):
        """200 and a JSON body while every entry point into Channels refuses.

        Asserted for every routable URL of every board, because the bed and
        emergency boards are each registered at two paths and a pin that
        covered one would leave the other free to become something else.
        """
        for url in BOARDS[board][2]:
            response = client_a.get(url)

            assert response.status_code == 200, (url, response.content)
            assert response["Content-Type"].startswith("application/json"), url
            assert isinstance(response.json(), list), url

    @pytest.mark.parametrize("board", sorted(BOARDS))
    def test_the_board_url_resolves_through_the_http_urlconf(self, board):
        """``resolve`` finds a DRF view action, not a socket route.

        The HTTP URLconf has no ``ws/`` prefix and the websocket router has no
        ``api/v1`` prefix, so "it answers 200" and "it is routed over HTTP" are
        separate claims and this is the second one — asserted by naming the
        viewset and the action the router bound.
        """
        viewset, action, urls = BOARDS[board]

        for url in urls:
            match = resolve(url)

            assert match.func.cls is viewset, url
            # Which action the router bound to *this* URL, read from DRF's own
            # ``as_view`` mapping rather than from ``BOARDS``. The previous
            # ``getattr(viewset, action, None)`` could not fail — ``action`` is
            # read out of ``BOARDS`` and the attribute is on the class by
            # construction — so it would have stayed green if a board path were
            # silently re-pointed at ``list`` or ``retrieve``.
            assert match.func.actions.get("get") == action, (url, match.url_name)
            # The route *name* the same URL is registered under, which is what
            # ``reverse()`` resolves. The explicit top-level aliases are
            # registered without the router's basename, so the name ends with
            # the action's hyphenated name rather than being equal to it —
            # ``tracking-board`` beside ``triage-tracking-board``.
            assert match.url_name.endswith(action.replace("_", "-")), (url, match.url_name)

    @pytest.mark.parametrize("board", sorted(BOARDS))
    def test_no_board_path_is_routed_by_the_websocket_router(self, board):
        """None of the board paths matches any socket route in the served table."""
        router = _asgi_websocket_router()

        for url in BOARDS[board][2]:
            assert _asgi_routes_matching(url) == [], url
            assert router.routes, "the served websocket router must not be empty"

    def test_the_http_urlconf_routes_no_websocket_path(self):
        """The two transports are disjoint by URL, not merely by convention."""
        for path in sorted(APPROVED_WEBSOCKET_ROUTES):
            with pytest.raises(Resolver404):
                resolve(f"/{path}")

    @pytest.mark.parametrize(
        "module", BOARD_VIEW_MODULES, ids=lambda module: module.__name__
    )
    def test_no_board_view_module_imports_channels(self, module):
        """Structural pin: a board view may not import Channels at all.

        Parsed rather than grepped. A substring check would be defeated by an
        ``import channels_redis``-style prefix in a comment, and — worse — it
        would not distinguish an import from a mention, so the cheapest way to
        silence this pin would be to reword the docstring. What is asserted is
        the set of modules the three board view modules actually import, which
        is what makes "a board quietly subscribed to a channel" impossible
        without an obvious edit here.
        """
        source = Path(module.__file__).read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(("." * node.level) + (node.module or ""))

        offenders = {
            name
            for name in imported
            if name.split(".")[0] == "channels" or name.endswith("consumers")
        }
        assert offenders == set(), f"{module.__name__} imports {offenders}"

    @pytest.mark.parametrize("board", sorted(BOARDS))
    def test_an_anonymous_board_read_is_refused(self, board, client_a):
        """Deny-by-default holds on the boards too.

        All three carry tenant-owned rows, so none may be reachable without a
        credential — 401 specifically, because ``IsAuthenticated`` runs before
        anything tenant-specific and an anonymous caller has claimed no tenant
        to be told it lacks.
        """
        for url in BOARDS[board][2]:
            response = APIClient().get(url)

            assert response.status_code == 401, (url, response.status_code)
            assert client_a.get(url).status_code == 200


class TestWebSocketRouteSet:
    """INT-012/PLT-008: exactly two socket routes, and no third (PLT-008)."""

    def test_the_routing_module_declares_exactly_the_two_approved_routes(self):
        """Asserted as a set, so neither an extra nor a missing route passes."""
        declared = {_route_path(route) for route in websocket_urlpatterns}

        assert declared == APPROVED_WEBSOCKET_ROUTES

    def test_each_approved_route_serves_its_own_consumer(self):
        """A route reachable but wired to the wrong consumer must fail here."""
        served = {
            _route_path(route): route.callback.consumer_class
            for route in websocket_urlpatterns
        }

        assert served == EXPECTED_CONSUMER_FOR

    def test_the_asgi_application_dispatches_only_http_and_websocket(self):
        """No third protocol branch, and HTTP is Django — not the socket router.

        A ``ProtocolTypeRouter`` entry is the only way a non-HTTP transport
        enters this application, so the *keys* are part of the boundary: an
        added ``"lifespan"`` or a third transport would otherwise arrive
        without touching a single line of ``apps.realtime.routing``.
        """
        mapping = asgi_application.application_mapping

        assert set(mapping) == {"http", "websocket"}
        assert isinstance(mapping["http"], ASGIHandler)

    def test_asgi_serves_the_routing_module_it_is_given_not_a_private_copy(self):
        """The served table *is* ``websocket_urlpatterns``.

        Identity, not equality. ``config.asgi.py`` passes the imported list
        straight to ``URLRouter``, so an inline second list declared in
        ``asgi.py`` — the way someone adds a third consumer while "just trying
        something" — leaves every other assertion in this file green while
        routing somewhere the app never declared.
        """
        router = _asgi_websocket_router()

        assert router.routes is websocket_urlpatterns
        assert {_route_path(route) for route in router.routes} == APPROVED_WEBSOCKET_ROUTES
        assert {
            _route_path(route): route.callback.consumer_class for route in router.routes
        } == EXPECTED_CONSUMER_FOR

    def test_no_board_path_and_no_unapproved_socket_path_is_routed(self):
        """The served router answers exactly the two approved paths."""
        candidates = set(BOARD_WEBSOCKET_CANDIDATES) | APPROVED_WEBSOCKET_ROUTES
        routed = {path for path in candidates if _asgi_routes_matching(path)}

        assert routed == APPROVED_WEBSOCKET_ROUTES

    @pytest.mark.parametrize("path", sorted(APPROVED_WEBSOCKET_ROUTES))
    def test_each_approved_route_is_live_in_the_running_application(self, path, context_a):
        """The set is not just declared — a real handshake reaches the consumer.

        Driven through ``config.asgi.application`` exactly as Task 22's suite
        drives it, so this agrees with that pin instead of restating it: the
        claim here is only that the route is wired, and it cannot be satisfied
        by a pattern that is present in the table but unreachable.
        """
        connected = _run(lambda: _handshake(f"/{path}", context_a["access"]))

        assert connected is True, f"{path} is in the routing table but unreachable"

    def test_an_unrouted_socket_path_reaches_no_consumer(self, context_a):
        """An unrouted path is refused by the served router, not merely unmatched.

        Carrying a *valid* token is what makes this meaningful: with a bogus
        one the Task 22 middleware closes the handshake at 4401 first, and the
        router is never consulted at all — so a pass here would prove only that
        auth works, not that no route exists for the path. Channels' outermost
        ``URLRouter`` raises ``ValueError("No route found for path ...")` when
        nothing matches, and that refusal is what is asserted here — pinned as a
        claim about the served application, driven through the real handshake
        machinery.
        """
        with pytest.raises(ValueError, match="No route found"):
            _run(lambda: _handshake("ws/beds/", context_a["access"]))


class TestBoardTenantScoping:
    """Horizontal isolation, asserted on identifiers rather than status codes."""

    @pytest.mark.parametrize("board", sorted(BOARDS))
    def test_a_tenant_sees_only_its_own_rows(self, board, client_a, client_b):
        """Both directions, with the foreign rows checked absent by id.

        Every row in both tenants is seeded first, so the assertion is not
        satisfied by an empty table: an unscoped queryset returns the *other*
        hospital's ids and fails here, and one that returned nothing for either
        would fail the "sees its own rows" half of the same test.
        """
        _, action, urls = BOARDS[board]
        own = {tenant: _rows_for(tenant) for tenant in (TENANT_A, TENANT_B)}

        for client, tenant_id in ((client_a, TENANT_A), (client_b, TENANT_B)):
            expected = own[tenant_id][action]
            foreign = [row for tenant, rows in own.items() if tenant != tenant_id
                       for row in rows[action]]

            for url in urls:
                response = client.get(url)

                assert response.status_code == 200, (url, response.content)
                returned = {row["id"] for row in response.json()}
                assert returned == set(expected), (url, returned)
                body = str(response.content)
                for row_id in foreign:
                    assert str(row_id) not in body, (url, row_id)

    def test_the_opd_queue_applies_its_own_waiting_filter(self, client_a):
        """A board's own documented filter is applied, not just its tenant scope.

        This is why :func:`_rows_for` seeds a *called* token per tenant. A queue
        that answered 200 with every token in the tenant would pass a
        status-code assertion and a tenant-scoping assertion, and would be wrong:
        the ER/OPD screen is a waiting-room queue, and a called or done token is
        not in it.
        """
        rows = _rows_for(TENANT_A)

        response = client_a.get(QUEUE_URL)

        assert response.status_code == 200, response.content
        returned = {row["id"] for row in response.json()}
        assert returned == set(rows["queue"])
        assert returned.isdisjoint(rows["not_in_queue"])

    def test_a_board_with_no_resolved_tenant_returns_nothing(
        self, context_a, context_b
    ):
        """Fail closed, not fail open.

        A caller who is authenticated but whose request resolves no tenant — the
        header absent and the credential dropped, so
        ``TenantBoundJWTAuthentication`` has no signed claim to bind — must get
        an empty board, never an unfiltered one. This is the
        ``TenantScopedQuerysetMixin`` contract the three boards inherit, pinned
        here because an empty 200 is indistinguishable from a working one until
        somebody asks what happens when the tenant is missing.
        """
        _rows_for(TENANT_A)
        client_a = APIClient()
        client_a.force_authenticate(user=context_b["user"])

        response = client_a.get(QUEUE_URL)

        assert response.status_code == 200, response.content
        assert response.json() == []


class TestEmergencyTrackingBoardFilters:
    """The query-parameter contract of the ER tracking board."""

    @pytest.fixture
    def triages(self, context_a):
        return [
            Triage.objects.create(
                tenant_id=context_a["tenant"].id, patient_id=uuid.uuid4(), category=cat
            )
            for cat in ("I", "II", "V")
        ]

    @pytest.mark.parametrize("url", TRACKING_BOARD_URLS)
    def test_category_filters_on_the_column_that_exists(self, client_a, triages, url):
        """``?category=`` is the primary parameter and filters ``Triage.category``.

        RED evidence for this file's whole reason to exist: the board used to
        filter on ``status``, a column ``Triage`` does not have, so every
        ``?status=`` request raised ``FieldError: Cannot resolve keyword
        'status' into field`` out of the view and answered 500. The IPD board
        docstring records the identical bug — ``facility_id`` on a model with no
        such column — and the same reasoning is applied here.
        """
        response = client_a.get(f"{url}?category=I")

        assert response.status_code == 200, response.content
        assert {row["id"] for row in response.json()} == {str(triages[0].id)}

    @pytest.mark.parametrize("url", TRACKING_BOARD_URLS)
    def test_status_is_a_documented_alias_for_category(self, client_a, triages, url):
        """``?status=`` keeps working and means the same thing.

        The OPD token queue legitimately uses ``?status=``, so a client that
        follows that convention across the operational boards must not meet a
        500 on its second board. The alias maps onto ``category`` rather than
        being refused: the value is a filter, and the board's job is to answer
        with the rows that match.
        """
        by_alias = client_a.get(f"{url}?status=II")
        by_parameter = client_a.get(f"{url}?category=II")

        assert by_alias.status_code == 200, by_alias.content
        assert by_alias.json() == by_parameter.json()
        assert {row["id"] for row in by_alias.json()} == {str(triages[1].id)}

    @pytest.mark.parametrize("url", TRACKING_BOARD_URLS)
    def test_an_unknown_value_is_an_empty_board_not_an_error(self, client_a, triages, url):
        """No value whitelist, matching the token queue's own behaviour.

        ``?status=nonsense`` on ``/api/v1/tokens/queue/`` answers 200 with an
        empty list today. The emergency board answers the same way, so a client
        sees one convention across both boards rather than a board that invents
        a stricter rule on one of them.
        """
        for parameter in ("category", "status"):
            response = client_a.get(f"{url}?{parameter}=VI")

            assert response.status_code == 200, response.content
            assert response.json() == []

    @pytest.mark.parametrize("url", TRACKING_BOARD_URLS)
    def test_both_parameters_agreeing_are_accepted(self, client_a, triages, url):
        """Redundant but consistent input filters once, not twice."""
        response = client_a.get(f"{url}?category=V&status=V")

        assert response.status_code == 200, response.content
        assert {row["id"] for row in response.json()} == {str(triages[2].id)}

    @pytest.mark.parametrize("url", TRACKING_BOARD_URLS)
    def test_both_parameters_disagreeing_is_a_400(self, client_a, triages, url):
        """A self-contradicting filter is refused, with wording that names it.

        Silently preferring one parameter would answer 200 to a request whose
        two halves ask for different things, and the caller would have no way
        to know which board they were looking at. The message is asserted as a
        literal rather than against the view's own constant, so rewording the
        refusal — a client matching on it — fails here.
        """
        response = client_a.get(f"{url}?category=I&status=V")

        assert response.status_code == 400, response.content
        # DRF coerces a scalar ``ValidationError`` detail into a one-element
        # list, which is the body shape every validation failure in this API
        # has; pinned literally so a rewording fails here.
        assert response.json() == [
            "category and status name different triage categories. 'status' "
            "is an alias for 'category' on this board; supply one or the "
            "other, not two different values."
        ]

    @pytest.mark.parametrize("url", TRACKING_BOARD_URLS)
    def test_the_board_is_ordered_newest_arrival_first(self, client_a, triages, url):
        """Ordering is preserved by the repair.

        The filter was rewritten; ``order_by("-arrival_time")`` is part of the
        board's contract — the ER screen shows the newest arrival at the top —
        so it is asserted rather than assumed.
        """
        response = client_a.get(url)

        assert [row["id"] for row in response.json()] == [
            str(triage.id) for triage in reversed(triages)
        ]

    def test_the_hyphenated_form_is_the_detail_route_and_not_the_board(self, client_a, triages):
        """``/api/v1/triages/tracking-board/`` 404s, and that is documented.

        DRF derives an action's ``url_name`` by hyphenating the method name
        (``tracking-board``) while leaving ``url_path`` underscored
        (``tracking_board``). A client that builds a URL from the route *name*
        therefore reaches the detail route with ``pk="tracking-board"``, which
        matches no UUID and answers 404. Pinned so the two routable forms stay
        the contract, and so the asymmetry is a recorded decision rather than a
        support ticket.
        """
        assert resolve("/api/v1/triages/tracking-board/").url_name == "triage-detail"

        response = client_a.get("/api/v1/triages/tracking-board/")

        assert response.status_code == 404, response.content
