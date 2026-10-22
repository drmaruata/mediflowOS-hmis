"""WebSocket handshake auth and consumer tenancy (PLT-001, INT-012).

The WebSocket path used to resolve its tenant from ``scope["user"]`` - an
attribute that never exists on ``auth.User`` - so ``connect()`` closed *every*
connection during the handshake and both approved consumers were unreachable.
This suite pins the replacement rule: the tenant comes from the access token's
signed ``tenant_id`` claim, exactly as
:class:`common.authentication.TenantBoundJWTAuthentication` does for REST, and a
handshake carrying no verifiable, tenant-bearing token is closed with 4401
before any consumer code runs.

It drives the **real** ASGI application (``config.asgi.application``) through
``channels.testing`` rather than a stub, because the defect being pinned down was
invisible to unit tests of the consumer alone: the middleware is what puts the
tenant into the scope, so a consumer-level test would have passed while every
real client was still turned away.

pytest-asyncio is not a declared dependency of this project and is not
configured (no ``asyncio_mode``, no marker), so the async communicator is driven
with asgiref's ``async_to_sync`` from sync tests rather than ``async def`` tests.
The whole interaction of one test lives inside a single inner coroutine: asgiref
runs that coroutine on its own event loop in its own thread, and the consumer's
task, its channel layer receives and its ``database_sync_to_async`` work all have
to stay on that same loop for the frames to be delivered at all.
"""
import asyncio
import time
import uuid
from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.identity_tenancy.models import Role, Tenant, UserMembership
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.platform.models import Notification
from apps.realtime.consumers import NotificationConsumer
from apps.realtime.routing import websocket_urlpatterns
from common.tenant import TENANT_CLAIM
from config.asgi import application

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

NOTIFICATIONS_URL = "/api/v1/notifications/"
NOTIFICATIONS_WS = "/ws/notifications/"
VITALS_WS = "/ws/vitals/"

#: WebSocket close code for a refused handshake. 4401 sits in the
#: application-defined range (4000-4999) and mirrors the 401 the same credential
#: would earn over REST, so a client can treat one auth failure identically on
#: both transports.
UNAUTHORIZED = 4401


@pytest.fixture
def tenant_a():
    """The tenant the first socket and the first REST client belong to."""
    return _make_tenant("Alpha Hospital")


@pytest.fixture
def tenant_b():
    """A second, unrelated hospital - the one no A socket may ever hear from."""
    return _make_tenant("Beta Hospital")


@pytest.fixture
def user_a(tenant_a):
    return _make_user(tenant_a, "alpha-nurse")


@pytest.fixture
def user_b(tenant_b):
    return _make_user(tenant_b, "beta-nurse")


@pytest.fixture
def token_a(user_a):
    """The access token socket A presents, carrying tenant A's signed claim."""
    return _access_token(user_a)


@pytest.fixture
def token_b(user_b):
    """Tenant B's token, for the client that writes B's notifications."""
    return _access_token(user_b)


def _run(scenario):
    """Drive one coroutine function to completion from this sync test.

    Everything a test needs from the socket has to happen inside the ``async
    def`` passed here: each ``async_to_sync`` call would otherwise run on a fresh
    event loop in a fresh thread, and the consumer's task - together with the
    channel layer queues it awaits - is bound to the loop that first ran it.
    """
    return async_to_sync(scenario)()


def _make_tenant(name):
    return Tenant.objects.create(name=name, slug=f"ws-{uuid.uuid4().hex[:8]}")


def _make_user(tenant, username):
    user = get_user_model().objects.create_user(
        username=username, password="ws-test-pass"
    )
    role = Role.objects.create(tenant=tenant, name=f"role-{username}", permissions=[])
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    return user


def _access_token(user, **claim_overrides):
    """A signed access token for ``user``, minted as the REST suite mints it.

    ``TenantAwareTokenSerializer`` is the production issuer, so the claims under
    test are the ones a real login produces. Overrides exist only to model the
    malformed credentials a handshake must refuse (no tenant claim, a claim for
    another tenant).
    """
    refresh = TenantAwareTokenSerializer.get_token(user)
    # ``RefreshToken.access_token`` is a property that builds a fresh access
    # token on every access, so the override has to be written to the same
    # object that is serialised - mutating one and encoding another silently
    # drops the override and leaves the issuer's real claim in place.
    access = refresh.access_token
    for claim, value in claim_overrides.items():
        access[claim] = value
    return str(access)


def _expired_access_token(user, tenant):
    """A correctly signed access token that expired an hour ago.

    Signature and claims are valid, so the only thing that can refuse it is the
    expiry check - a middleware that validated the signature alone would accept
    this connection forever.
    """
    token = AccessToken()
    token["user_id"] = str(user.id)
    token[TENANT_CLAIM] = str(tenant.id)
    token.set_exp(lifetime=timedelta(hours=-1))
    return str(token)


def _client(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _notification_payload(user, title):
    """A notification create body.

    ``Notification.user_id`` is a UUIDField while ``auth.User`` keeps Django's
    integer primary key, so the int is coerced the way every writer of that
    column coerces it (see ``test_authentication._uuid_pk``); posting the raw
    int is a 400.
    """
    return {
        "user_id": str(uuid.UUID(int=user.pk)),
        "title": title,
        "body": "antibiotic due",
        "type": "alert",
    }


def _delivered_flag(tenant_id, notification_id):
    """Read the delivery flag straight from the row, not from the API response.

    The API response is written before the push happens, so it cannot show the
    consumer's write; only a re-read can.
    """
    return (
        Notification.objects.filter(tenant_id=tenant_id, id=notification_id)
        .values_list("delivered", flat=True)
        .first()
    )


async def _await_delivered(tenant_id, notification_id, timeout=5.0):
    """Wait for the connected consumer to flip ``delivered`` on the row.

    The consumer sends the frame *then* marks the row, so a test that read the
    row the instant the frame arrived could legitimately observe the pre-flip
    value and flake. This turns that ordering into a bounded wait: the flag is
    set by a ``database_sync_to_async`` update that lands on this test's own
    thread, and the wait fails loudly (returns False) if it never arrives.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await sync_to_async(_delivered_flag)(tenant_id, notification_id):
            return True
        await asyncio.sleep(0.05)
    return False


def _handshake(path, query=""):
    """Drive one handshake through the real ASGI application, then close it."""
    async def scenario():
        communicator = WebsocketCommunicator(application, f"{path}{query}")
        result = await communicator.connect()
        await communicator.disconnect()
        return result

    return _run(scenario)


class TestHandshakeAuthentication:
    """A handshake without a tenant-carrying token never reaches a consumer."""

    def test_valid_token_is_accepted(self, tenant_a, token_a):
        """Regression pin: a well-formed token must open the socket.

        Before this task every handshake was closed, because ``connect()`` read
        ``scope["user"].tenant_id`` - an attribute ``auth.User`` does not have -
        so the tenant resolved to None and the consumer closed itself. This test
        is that failure: it passes only when the middleware is what supplies the
        tenant.
        """
        async def scenario():
            communicator = WebsocketCommunicator(
                application, f"{NOTIFICATIONS_WS}?token={token_a}"
            )
            connected, _ = await communicator.connect()
            await communicator.disconnect()
            return connected

        assert _run(scenario) is True

    def test_handshake_without_a_token_is_closed(self):
        result = _handshake(NOTIFICATIONS_WS)
        assert result == (False, UNAUTHORIZED)

    def test_handshake_with_a_garbage_token_is_closed(self):
        result = _handshake(NOTIFICATIONS_WS, "?token=not-a-jwt")
        assert result == (False, UNAUTHORIZED)

    def test_handshake_with_an_expired_token_is_closed(self):
        tenant = _make_tenant("Expiry Hospital")
        user = _make_user(tenant, "expired-nurse")
        result = _handshake(
            NOTIFICATIONS_WS, f"?token={_expired_access_token(user, tenant)}"
        )
        assert result == (False, UNAUTHORIZED)

    def test_handshake_with_a_token_that_carries_no_tenant_is_closed(self):
        """A token with no tenant claim must fail closed, not default.

        ``TenantAwareTokenSerializer`` issues such a token for a real account
        with no membership. Over REST that clears the context and the caller sees
        nothing; over a socket there is no request to scope, so the handshake is
        refused rather than the connection being attached to no tenant at all.
        """
        tenant = _make_tenant("Claimless Hospital")
        user = _make_user(tenant, "claimless-nurse")
        token = _access_token(user, **{TENANT_CLAIM: None})
        assert _handshake(NOTIFICATIONS_WS, f"?token={token}") == (False, UNAUTHORIZED)

    def test_handshake_for_an_unknown_user_is_closed(self):
        tenant = _make_tenant("Ghost Hospital")
        token = RefreshToken()
        token["user_id"] = "999999"
        token[TENANT_CLAIM] = str(tenant.id)
        assert _handshake(
            NOTIFICATIONS_WS, f"?token={str(token.access_token)}"
        ) == (False, UNAUTHORIZED)

    def test_handshake_for_an_inactive_user_is_closed(self):
        tenant = _make_tenant("Dormant Hospital")
        user = _make_user(tenant, "dormant-nurse")
        user.is_active = False
        user.save(update_fields=["is_active"])
        token = _access_token(user)
        assert _handshake(NOTIFICATIONS_WS, f"?token={token}") == (False, UNAUTHORIZED)

    def test_disconnect_after_a_refused_handshake_does_not_raise(self):
        """A refused handshake still tears down cleanly.

        The middleware returns without ever calling the consumer, and the
        communicator's ``disconnect`` re-enters the application stack. Nothing
        there may raise, or a client's normal close on a rejected socket would
        surface as a server error.
        """
        async def scenario():
            communicator = WebsocketCommunicator(application, NOTIFICATIONS_WS)
            result = await communicator.connect()
            await communicator.disconnect()
            return result

        assert _run(scenario) == (False, UNAUTHORIZED)


class TestConsumerTeardown:
    """The consumers must survive a connect() that never reached the group."""

    def test_disconnect_after_an_early_closed_connect_does_not_raise(self):
        """Pin the unbound-attribute bug in ``disconnect()``.

        ``disconnect()`` used to reference ``self.group``, which was only bound
        *after* the tenant check in ``connect()``. A connection that closed
        during the handshake therefore raised AttributeError in teardown. The
        consumer is driven directly here, with no middleware to have set the
        tenant, precisely to reconstruct that path.
        """
        async def scenario():
            communicator = WebsocketCommunicator(
                NotificationConsumer.as_asgi(), NOTIFICATIONS_WS
            )
            accepted, _ = await communicator.connect()
            await communicator.disconnect()
            return accepted

        assert _run(scenario) is False


class TestNotificationDelivery:
    """A persisted notification is pushed to its tenant's sockets and flagged."""

    def test_posted_notification_reaches_the_socket_and_is_flagged_delivered(
        self, tenant_a, token_a, user_a
    ):
        client = _client(token_a)
        payload = _notification_payload(user_a, "vancomycin level")

        async def scenario():
            communicator = WebsocketCommunicator(
                application, f"{NOTIFICATIONS_WS}?token={token_a}"
            )
            connected, _ = await communicator.connect()
            assert connected is True
            response = await sync_to_async(client.post)(
                NOTIFICATIONS_URL, payload, format="json"
            )
            assert response.status_code == 201, response.content
            message = await communicator.receive_json_from(timeout=5)
            await communicator.disconnect()
            return response.json(), message

        created, message = _run(scenario)

        # The API creates an in-app notification, so the row is persisted by the
        # server rather than at the client's discretion (PLT-001).
        assert created["persisted"] is True
        assert created["delivered"] is False
        assert message["id"] == created["id"]

        assert async_to_sync(_await_delivered)(
            tenant_a.id, created["id"]
        ) is True, (
            "the connected consumer must flip delivered once it sends the row"
        )
        row = Notification.objects.get(tenant_id=tenant_a.id, id=created["id"])
        assert row.delivered is True
        assert row.persisted is True

    def test_client_cannot_claim_delivery_on_create(self, tenant_a, token_a, user_a):
        """``persisted``/``delivered`` are server-owned, so a client cannot set them.

        A caller who could write ``delivered: true`` would mark an alert as
        received without any socket ever receiving it.
        """
        client = _client(token_a)
        payload = _notification_payload(user_a, "untrusted claim")
        payload["persisted"] = False
        payload["delivered"] = True

        response = client.post(NOTIFICATIONS_URL, payload, format="json")

        assert response.status_code == 201, response.content
        assert response.json()["persisted"] is True
        assert response.json()["delivered"] is False
        assert _delivered_flag(tenant_a.id, response.json()["id"]) is False


class TestTenantIsolation:
    """Two tenants' sockets must never see each other's rows."""

    def test_a_notification_never_crosses_the_tenant_boundary(
        self, tenant_a, tenant_b, token_a, token_b, user_a, user_b
    ):
        client_a = _client(token_a)
        client_b = _client(token_b)

        async def scenario():
            socket_a = WebsocketCommunicator(
                application, f"{NOTIFICATIONS_WS}?token={token_a}"
            )
            socket_b = WebsocketCommunicator(
                application, f"{NOTIFICATIONS_WS}?token={token_b}"
            )
            assert (await socket_a.connect())[0] is True
            assert (await socket_b.connect())[0] is True

            created_a = await sync_to_async(client_a.post)(
                NOTIFICATIONS_URL,
                _notification_payload(user_a, "alpha alert"),
                format="json",
            )
            assert created_a.status_code == 201, created_a.content
            received_a = await socket_a.receive_json_from(timeout=5)
            assert received_a["id"] == created_a.json()["id"]

            # Tenant B's socket must hear nothing: the push is addressed to
            # tenant A's group only.
            assert (await socket_b.receive_nothing(timeout=0.5, interval=0.05)) is True

            created_b = await sync_to_async(client_b.post)(
                NOTIFICATIONS_URL,
                _notification_payload(user_b, "beta alert"),
                format="json",
            )
            assert created_b.status_code == 201, created_b.content
            received_b = await socket_b.receive_json_from(timeout=5)
            assert received_b["id"] == created_b.json()["id"]
            assert (await socket_a.receive_nothing(timeout=0.5, interval=0.05)) is True

            await socket_a.disconnect()
            await socket_b.disconnect()
            return created_a.json(), created_b.json()

        row_a, row_b = _run(scenario)

        assert async_to_sync(_await_delivered)(tenant_a.id, row_a["id"]) is True
        assert async_to_sync(_await_delivered)(tenant_b.id, row_b["id"]) is True

    def test_a_socket_opened_for_one_tenant_never_receives_another_tenants_push(
        self, tenant_a, tenant_b, token_a, token_b, user_b
    ):
        """The isolation pin, with the foreign push driven by the other tenant.

        Tenant B's notification is written through B's own authenticated client,
        so both the row and the group message are addressed to B. A socket whose
        token claims tenant A must not receive it.
        """
        client_b = _client(token_b)

        async def scenario():
            communicator = WebsocketCommunicator(
                application, f"{NOTIFICATIONS_WS}?token={token_a}"
            )
            assert (await communicator.connect())[0] is True
            response = await sync_to_async(client_b.post)(
                NOTIFICATIONS_URL,
                _notification_payload(user_b, "beta only"),
                format="json",
            )
            assert response.status_code == 201, response.content
            assert (await communicator.receive_nothing(timeout=0.5, interval=0.05)) is True
            await communicator.disconnect()
            return response.json()

        row_b = _run(scenario)
        assert row_b["persisted"] is True
        # No socket was connected for tenant B, so its row stays undelivered -
        # which is what proves the tenant-A socket did not mark it either.
        assert _delivered_flag(tenant_b.id, row_b["id"]) is False


class TestVitalsRoute:
    """INT-012 allows exactly two consumers; both share the auth rule."""

    def test_vitals_route_accepts_the_same_token(self, tenant_a, token_a):
        async def scenario():
            communicator = WebsocketCommunicator(
                application, f"{VITALS_WS}?token={token_a}"
            )
            connected, _ = await communicator.connect()
            await communicator.disconnect()
            return connected

        assert _run(scenario) is True

    def test_vitals_route_rejects_a_handshake_without_a_token(self):
        assert _handshake(VITALS_WS) == (False, UNAUTHORIZED)


class TestRoutingTable:
    """INT-012: the WebSocket surface is exactly the two approved routes."""

    def test_the_routing_table_holds_exactly_the_two_int_012_routes(self):
        routes = websocket_urlpatterns
        assert [route.pattern.regex.pattern for route in routes] == [
            "ws/notifications/$",
            "ws/vitals/$",
        ]
        assert routes[0].pattern.match("ws/notifications/")
        assert routes[1].pattern.match("ws/vitals/")
        # A third consumer must fail here rather than quietly widen the surface.
        assert routes[0].pattern.match("ws/vitals/") is None
