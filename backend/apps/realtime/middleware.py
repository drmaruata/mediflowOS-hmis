"""JWT authentication for the WebSocket handshake (PLT-001, INT-012).

Why the token travels on the query string
-----------------------------------------
A browser's WebSocket handshake cannot carry an Authorization header: the API
that creates the socket takes a URL and nothing else, so there is nowhere to put
one. The access token is therefore read from the ``token`` query parameter of
the upgrade request, which is the only channel available to the shipped client.

The tradeoff is real and taken knowingly: query strings are recorded in reverse
proxy logs, load balancer access logs and browser history. It is survivable here
because the credential is the same *short-lived access token* (15 minutes,
``SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]``) that REST already accepts in a header -
not a refresh token, which outlives the session and rotates into a new one. A
leaked access token expires quickly and is blacklisted on rotation. Nothing
longer-lived than an access token belongs on a query string.

Why the tenant comes from the token and not from the user record
---------------------------------------------------------------
This mirrors :class:`common.authentication.TenantBoundJWTAuthentication`, and for
the same reason: the tenant is read from the token's **signed** ``tenant_id``
claim, never from an attribute of the resolved user. The consumer that used to
read ``scope["user"].tenant_id`` was reading an attribute ``auth.User`` does not
have, so every connection closed before this module existed. Reading a tenant
off the user record is wrong twice over - the attribute is not there, and if it
were, a caller could assert a tenant they were not issued one for.

A handshake that cannot be authenticated is refused with close code 4401 before
any consumer code runs, so an unauthenticated client never reaches a group.
"""
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken

from common.tenant import TENANT_CLAIM

logger = logging.getLogger(__name__)

#: WebSocket close code for a refused handshake. 4401 sits in the
#: application-defined range (4000-4999) and mirrors the HTTP 401 the same
#: credential would earn over REST, so a client can treat one authentication
#: failure identically on both transports.
UNAUTHORIZED_CLOSE_CODE = 4401

#: Query parameter the upgrade request carries the access token in.
TOKEN_PARAMETER = "token"


def _presented_token(scope) -> str:
    """The raw token from the query string, or an empty string.

    ``parse_qs`` is handed the decoded string because a percent-encoded value has
    to be decoded before SimpleJWT sees it, and a query string that is not valid
    UTF-8 must not raise here: it cannot contain a usable token, so decoding
    failure and a missing parameter are the same refusal.
    """
    raw_query = scope.get("query_string") or b""
    try:
        query = raw_query.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    return (parse_qs(query).get(TOKEN_PARAMETER) or [""])[0]


def _active_user(user_id):
    """The active user a token's user claim names, or ``None``.

    Runs under ``database_sync_to_async``: the middleware is async, the ORM is
    not. The user id arrives inside a signed claim, so it is still input - a
    value that is not a valid primary key is a refusal, not an exception.
    """
    if not user_id:
        return None
    user_model = get_user_model()
    try:
        return user_model.objects.get(pk=user_id, is_active=True)
    except (user_model.DoesNotExist, ValueError, TypeError):
        return None


async def _reject(send, scope, reason):
    """Close the handshake with 4401, logging the path and the reason only.

    The token is deliberately absent from the log line: it is a bearer
    credential, and a log line holding one is a log line holding a session.
    """
    logger.warning(
        "websocket handshake refused path=%s reason=%s", scope.get("path"), reason
    )
    await send({"type": "websocket.close", "code": UNAUTHORIZED_CLOSE_CODE})


def token_auth_middleware(inner):
    """Authenticate a WebSocket handshake from its access token.

    Returns an ASGI application that checks the token and either puts the
    authenticated user and the token's tenant into the scope - as
    ``scope["tenant_id"]``, which is the only place the consumers read it from -
    or closes the connection with :data:`UNAUTHORIZED_CLOSE_CODE`.

    Wired in ``config/asgi.py`` as
    ``token_auth_middleware(URLRouter(websocket_urlpatterns))``, replacing
    ``AuthMiddlewareStack``: session authentication cannot carry a tenant claim,
    and both consumers need an authenticated tenant-scoped connection.
    """

    async def middleware(scope, receive, send):
        token = _presented_token(scope)
        if not token:
            await _reject(send, scope, "no token presented")
            return

        try:
            access = AccessToken(token)
        except TokenError:
            # One except, two failures: a tampered or malformed signature
            # (InvalidToken) and an expired access token (ExpiredTokenError) are
            # both TokenError, and neither may be distinguished in the log - a
            # caller must not be able to tell "expired" from "forged".
            await _reject(send, scope, "token failed validation")
            return

        # SimpleJWT 5.x made Token a plain class rather than a dict subclass, so
        # the claims are read off ``payload``. An ``isinstance(token, dict)``
        # check would silently evaluate false and every claim would read as
        # absent - the quiet failure common/authentication.py documents.
        claims = getattr(access, "payload", None)
        claims = claims if isinstance(claims, dict) else {}

        user = await database_sync_to_async(_active_user)(
            claims.get(api_settings.USER_ID_CLAIM)
        )
        if user is None:
            await _reject(send, scope, "no active user for the token's user claim")
            return

        tenant_id = claims.get(TENANT_CLAIM)
        if not tenant_id:
            # A real account with no active membership. Over REST that account
            # has its context cleared and sees nothing; over a socket there is no
            # request to scope, so the handshake is refused rather than the
            # connection being attached to no tenant at all.
            await _reject(send, scope, "token carries no tenant claim")
            return

        scope["user"] = user
        scope["tenant_id"] = str(tenant_id)
        return await inner(scope, receive, send)

    return middleware
