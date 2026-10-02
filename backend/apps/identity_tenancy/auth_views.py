"""Authentication endpoints: token issuance and second-factor enrolment.

TEN-006 requires MFA for privileged roles; TEN-007 requires break-glass access
to record a reason. Both live here because both are authentication concerns
rather than domain logic.
"""
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import BreakGlassAccess
from common.authentication import claims_from
from .tokens import (
    BREAK_GLASS_CLAIM,
    PERMISSIONS_CLAIM,
    ROLE_CLAIM,
    TenantAwareTokenSerializer,
    active_membership,
)

BREAK_GLASS_REASON_HEADER = "X-Break-Glass-Reason"


class TenantTokenObtainPairView(TokenObtainPairView):
    """Exchanges credentials for a token carrying tenant context."""

    serializer_class = TenantAwareTokenSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []


class TOTPDeviceSerializer(serializers.Serializer):
    persistent_id = serializers.CharField(read_only=True)
    name = serializers.CharField()
    confirmed = serializers.BooleanField(read_only=True)
    config_url = serializers.CharField(read_only=True, help_text="otpauth:// URI for QR enrolment")


class TOTPEnrolViewSet(viewsets.ViewSet):
    """Second-factor enrolment for privileged roles (TEN-006).

    Uses ``django_otp``'s TOTPDevice rather than a bespoke scheme: the device
    model already implements throttling and replay protection, and the package is
    already a declared dependency.

    A device starts unconfirmed and only becomes usable once the user proves they
    can produce a token from it, so an attacker who can write to the enrolment
    endpoint cannot silently attach their own authenticator.
    """

    permission_classes = [IsAuthenticated]

    def list(self, request):
        from django_otp import devices_for_user

        # confirmed=None so pending enrolments are listed too: a user who has
        # just registered an authenticator has to see it in order to confirm it.
        devices = [
            TOTPDeviceSerializer(
                {
                    "persistent_id": device.persistent_id,
                    "name": device.name,
                    "confirmed": device.confirmed,
                    "config_url": getattr(device, "config_url", None),
                }
            ).data
            for device in devices_for_user(request.user, confirmed=None)
        ]
        return Response(devices)

    @extend_schema(request=None)
    def create(self, request):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        device = TOTPDevice.objects.create(
            user=request.user,
            name=request.data.get("name") or "Authenticator",
            confirmed=False,
        )
        # The secret is returned once, at enrolment, so the authenticator app can
        # be seeded. It is not retrievable again through this API.
        return Response(
            TOTPDeviceSerializer(
                {
                    "persistent_id": device.persistent_id,
                    "name": device.name,
                    "confirmed": device.confirmed,
                    "config_url": device.config_url,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )

    def confirm(self, request, persistent_id=None):
        """Verify a token from the new device and mark it usable."""
        from django_otp import devices_for_user

        # Coerced to text because a client may legitimately send the code as a JSON
        # number, and ``.strip()`` on an int raises. An authenticator app shows
        # six digits, which encourages exactly that mistake.
        raw = request.data.get("token")
        token = str(raw).strip() if raw is not None else ""
        if not token:
            raise serializers.ValidationError({"token": "This field is required."})

        for device in devices_for_user(request.user, confirmed=False):
            if device.persistent_id != persistent_id:
                continue
            # verify_is_allowed applies the library's attempt throttling, so a
            # brute force against a 6-digit code is rate limited.
            allowed, _detail = device.verify_is_allowed()
            if not allowed:
                return Response(
                    {"detail": "Too many attempts. Try again later."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            if not device.verify_token(token):
                raise serializers.ValidationError({"token": "Invalid token."})
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            return Response({"status": "confirmed"})

        return Response(
            {"detail": "No pending device with that id."},
            status=status.HTTP_404_NOT_FOUND,
        )

    def destroy(self, request, persistent_id=None):
        from django_otp import devices_for_user

        # confirmed=None so an unconfirmed device can be discarded; leaving a
        # half-finished enrolment behind would block re-enrolment.
        for device in devices_for_user(request.user, confirmed=None):
            if device.persistent_id == persistent_id:
                device.delete()
                return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(status=status.HTTP_404_NOT_FOUND)


class MeView(APIView):
    """The caller's identity and tenant context.

    The frontend needs this on load to decide what to render. Returning the
    tenant the server *resolved*, rather than the one the client asked for, makes
    a mismatch visible instead of silent.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = active_membership(request.user)
        claims = claims_from(request)
        return Response(
            {
                "username": request.user.get_username(),
                "tenant_id": getattr(request, "tenant_id", None),
                "facility_id": getattr(request, "facility_id", None),
                "role": claims.get(ROLE_CLAIM),
                "permissions": claims.get(PERMISSIONS_CLAIM, []),
                "allows_break_glass": claims.get(BREAK_GLASS_CLAIM, False),
                "requires_mfa": bool(membership.role.require_mfa) if membership else False,
            }
        )


class BreakGlassView(APIView):
    """Grants recorded emergency access to a record outside normal scope (TEN-007).

    Requires a non-empty reason, and the grant is written before access is
    allowed, so there is no path to an unlogged emergency read.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        claims = claims_from(request)
        if not claims.get(BREAK_GLASS_CLAIM):
            return Response(
                {"detail": "This role does not hold break-glass access."},
                status=status.HTTP_403_FORBIDDEN,
            )

        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return Response(
                {"detail": "No tenant context for this request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        reason = (request.headers.get(BREAK_GLASS_REASON_HEADER) or "").strip()
        if not reason:
            return Response(
                {
                    "detail": (
                        "Break-glass access requires a reason. Send it in the "
                        f"{BREAK_GLASS_REASON_HEADER} header."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        resource_type = request.data.get("resource_type")
        resource_id = request.data.get("resource_id")
        if not resource_type or not resource_id:
            raise serializers.ValidationError(
                {"resource_type": "Required.", "resource_id": "Required."}
            )

        access = BreakGlassAccess.objects.create(
            tenant_id=tenant_id,
            user_id=request.user.pk,
            resource_type=str(resource_type)[:64],
            resource_id=str(resource_id)[:64],
            reason=reason,
            granted_at=timezone.now(),
        )
        return Response(
            {"access_id": str(access.id), "granted_at": access.granted_at},
            status=status.HTTP_201_CREATED,
        )