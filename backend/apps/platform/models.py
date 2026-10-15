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


class FeatureFlag(models.Model):
    """One per-tenant feature switch (PLT-006).

    Re-added by migration ``0007`` after ``0005`` dropped the model with
    ``DeleteModel``. The re-add is a new ``CreateModel``, never a restoration of
    the deleted table's definition: a migration must apply the same DDL it
    applied when it was written, and the field set below is the model's *current*
    state, not the one ``0001`` happened to create.

    The row level security policy that ``0004`` attached to this table died with
    it - PostgreSQL drops a table's policies when the table is dropped - so the
    same migration re-enables it. Without that, the table would be created with
    no policy while the registry still recorded ``0004`` as covering it: the one
    failure nothing downstream reports, because RLS is DDL with no model state.

    ``key`` is the feature's name in code and ``enabled`` its state for this
    tenant alone. The pair is unique *per tenant*, not globally: two hospitals
    rolling the same feature out at different times is the ordinary case, and a
    global uniqueness constraint would make the second one a conflict.

    ``enabled`` defaults to ``False`` and the read helper fails closed, so a
    feature nobody configured is off rather than on.

    ``description`` is free text an administrator writes for other humans. It is
    ``NOT NULL`` with an empty-string default rather than nullable: "no
    description" would otherwise have two spellings that every reader has to
    handle, and ``NULL`` is not a state anyone sets deliberately.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    key = models.CharField(max_length=64)
    enabled = models.BooleanField(default=False)
    description = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "platform.feature_flag"
        unique_together = [["tenant_id", "key"]]
        # The unique index above leads with tenant_id and already covers both
        # lookups this table has - the tenant-scoped list and the (tenant, key)
        # probe - so this declaration repeats the intent explicitly rather than
        # relying on what a unique index happens to cover. SetupProgress and
        # ReferenceData declare theirs the same way.
        indexes = [models.Index(fields=["tenant_id", "key"])]


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
    uuid (36), a separator, and a sanitised filename of at most 81 characters
    (the :data:`MAX_FILENAME_LENGTH` budget of 80 plus the dot and extension the
    truncation preserves) - see ``apps.platform.views`` for the cap and the
    arithmetic, which comes to 155 at worst.

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
