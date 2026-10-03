"""App config for the shared health probe."""
from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "apps.common"
    label = "apps_common"

    def ready(self):
        """Register the OpenAPI authentication extension.

        drf-spectacular builds its authentication-extension registry when the
        extension classes are *defined*, and it resolves that registry while
        generating the schema. Nothing else in this project imports
        ``common.schema``, so without this import the registry has no entry for
        :class:`common.authentication.TenantBoundJWTAuthentication` and every
        viewset warns that its authenticator could not be resolved - leaving the
        published schema with no security scheme at all.

        ``ready()`` is the right hook rather than a SPECTACULAR setting: it runs
        after Django has configured DRF, whereas importing at settings-module
        level configures DRF's schema class prematurely and breaks the
        SpectacularAPIView's own schema. See common/schema.py.
        """
        from common import schema  # noqa: F401

        from common.observability import setup_observability
        setup_observability()
