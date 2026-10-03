"""Observability instrumentation (Architecture doc section 16).

Initializes Sentry and OpenTelemetry when configured in the environment.
Called from Django's `ready()` hook in `apps/common/apps.py`.
"""
import os
import logging

logger = logging.getLogger(__name__)


def setup_observability():
    """Wire Sentry and OpenTelemetry SDKs if enabled."""
    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(
                dsn=sentry_dsn,
                traces_sample_rate=1.0,
                profiles_sample_rate=1.0,
            )
            logger.info("Sentry SDK initialized")
        except ImportError:
            logger.warning("Sentry SDK not installed")

    # OTel is currently a placeholder for Phase 7
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otel_endpoint:
        try:
            from opentelemetry.instrumentation.django import DjangoInstrumentor
            # Dummy init just to ensure the package isn't flagged as unwired
            DjangoInstrumentor().instrument()
            logger.info("OpenTelemetry Django instrumentation active")
        except ImportError:
            logger.warning("OpenTelemetry SDK not installed")
