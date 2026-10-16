"""App config for the shared health probe."""
from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "apps.common"
    label = "apps_common"

    def ready(self):
        """Register the OpenAPI authentication extension.

        drf-spectacular resolves its authentication-extension registry while
        generating the schema, and nothing else in this project imports
        ``common.schema`` — so without this import the registry has no entry for
        :class:`common.authentication.TenantBoundJWTAuthentication`, every viewset
        warns that its authenticator could not be resolved, and the published
        schema carries no security scheme at all.

        ``ready()`` rather than a ``SPECTACULAR_SETTINGS`` hook: it runs after
        Django has configured DRF, whereas importing at settings-module level
        configures DRF's schema class prematurely and breaks the
        SpectacularAPIView's own schema. See ``common/schema.py``.
        """
        from common import schema  # noqa: F401

        from common.observability import setup_observability
        setup_observability()
