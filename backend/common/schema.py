"""OpenAPI schema generation.

drf-spectacular registers an authentication extension when the class is
*defined*, so this module only takes effect once something imports it. Nothing
else in the project does, so :meth:`apps.common.apps.CommonConfig.ready` imports
it during app loading — deliberately not from a ``SPECTACULAR_SETTINGS`` hook,
because importing at settings-module level configures DRF's schema class
prematurely and breaks the SpectacularAPIView's own schema. See that AppConfig
for the reasoning.

Why an extension is needed at all: drf-spectacular matches an authentication
class by exact identity, so its bundled ``SimpleJWTScheme`` does not cover
:class:`common.authentication.TenantBoundJWTAuthentication` even though that
class subclasses simplejwt's ``JWTAuthentication``. Without this, every viewset
emits a "could not resolve authenticator" warning and the published schema
documents no security scheme at all - Swagger UI would present an authenticated
API as anonymous, which is the wrong thing to tell an integrator.

The wire format is unchanged from simplejwt: a ``Bearer`` JWT. What our class
adds is tenant binding, a request-scoped concern with no schema representation.
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.plumbing import build_bearer_security_scheme_object


class TenantBoundJWTScheme(OpenApiAuthenticationExtension):
    target_class = "common.authentication.TenantBoundJWTAuthentication"
    name = "jwtAuth"
    # Match by inheritance too, so a future subclass of the authenticator is
    # still documented rather than silently losing its security scheme.
    match_subclasses = True

    def get_security_definition(self, auto_schema):
        from rest_framework_simplejwt.settings import api_settings

        return build_bearer_security_scheme_object(
            header_name=getattr(api_settings, "AUTH_HEADER_NAME", "HTTP_AUTHORIZATION"),
            token_prefix=api_settings.AUTH_HEADER_TYPES[0],
            bearer_format="JWT",
        )


def preprocess_register_extensions(endpoints, **kwargs):
    """Kept for callers that prefer to import this module via SPECTACULAR_SETTINGS hooks."""
    return endpoints
