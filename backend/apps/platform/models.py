"""Platform models (PLT-001 to PLT-008)."""
from django.db import models
import uuid


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    user_id = models.UUIDField(db_index=True)
    title = models.CharField(max_length=400)
    body = models.TextField()
    type = models.CharField(max_length=32)  # alert | info | critical
    persisted = models.BooleanField(default=False)
    delivered = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform.notification"
        indexes = [models.Index(fields=["tenant_id", "user_id", "read_at"])]


class PlatformFile(models.Model):
    """A stored document (PLT-005).

    Access control is not a column here: it is the tenant partition in the
    storage path, the tenant-scoped queryset on the viewset, and the row level
    security policy on ``platform.file``. A document is reachable only by the
    hospital that uploaded it, and the download route never resolves a path a
    row did not supply.

    ``file_url`` is a :class:`~django.db.models.URLField` holding a *relative
    storage path* - ``<tenant_id>/<upload uuid>/<sanitised filename>`` - rather
    than a URL. It stays a URLField so this model needs no migration: the
    field's application-level validators only run through ``full_clean``, which
    the ORM's ``create()`` does not call, so a value the view derives after
    validation is written verbatim. The stored path fits the column's
    200 characters by construction - a tenant uuid (36), a separator, an upload
    uuid (36), a separator and at most :data:`MAX_FILENAME_LENGTH` characters
    of sanitised filename (80) - see ``apps.platform.views`` for the cap and
    the arithmetic.

    ``uploaded_by`` is a ``UUIDField`` holding the coerced pk of the
    authenticated principal, not a foreign key: the application users live in
    ``auth.User``, which is deliberately outside the tenant schemas.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    filename = models.CharField(max_length=500)
    file_url = models.URLField()
    file_type = models.CharField(max_length=64)
    uploaded_by = models.UUIDField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform.file"
        indexes = [models.Index(fields=["tenant_id", "uploaded_at"])]


class ScheduledJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    job_type = models.CharField(max_length=64)  # indicator_computation | report_generation | sync
    status = models.CharField(max_length=16, default="pending")  # pending | running | completed | failed
    scheduled_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "platform.scheduled_job"
        indexes = [models.Index(fields=["tenant_id", "status", "scheduled_at"])]
