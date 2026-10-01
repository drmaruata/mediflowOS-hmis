"""Throttling policies keyed on gateway identity rather than on session.

Architecture doc section 8.4 requires rate limiting per HIP ID for ABDM
callbacks. Those callbacks carry no user JWT, so they fall under the shared
anonymous budget in the default configuration. A single misbehaving or
compromised facility could then exhaust that budget and starve every other
tenant's registrations.
"""
from rest_framework.throttling import SimpleRateThrottle

# ABDM gateway callbacks identify the calling facility by HIP. Both spellings
# are accepted because the exact gateway contract must be confirmed against
# ABDM sandbox documentation at build time (architecture doc section 8.2,
# "Version caution").
HIP_HEADERS = ("X-Hip-Id", "X-HIP-ID")
HIP_PAYLOAD_KEYS = ("hipId", "hip_id", "hip")


def resolve_hip_id(request) -> str | None:
    """Best-effort identification of the calling facility.

    Returns ``None`` when the request carries no usable HIP identifier, so
    callers can fall back to a less specific key rather than failing.
    """
    for header in HIP_HEADERS:
        value = request.headers.get(header)
        if value:
            return value

    # Fall back to the payload. Accessing ``request.data`` inside a throttle is
    # safe: DRF caches the parsed result, so the view reads it from the cache.
    try:
        payload = request.data
    except Exception:
        return None

    if isinstance(payload, dict):
        for key in HIP_PAYLOAD_KEYS:
            value = payload.get(key)
            if value:
                return str(value)
    return None


class AbdmHipThrottle(SimpleRateThrottle):
    """Throttle ABDM profile-share callbacks per HIP ID.

    Requests without a recognisable HIP ID are keyed on the client address.
    That is intentionally weaker, but it stops an anonymous flood from
    bypassing the limit simply by omitting the header.
    """

    scope = "abdm_callback"

    def get_cache_key(self, request, view):
        hip_id = resolve_hip_id(request)
        if hip_id:
            ident = f"hip:{hip_id}"
        else:
            ident = f"addr:{self.get_ident(request)}"
        return self.cache_format % {"scope": self.scope, "ident": ident}