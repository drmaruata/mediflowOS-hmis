"""Platform serializers."""
from django.conf import settings
from django.core.validators import FileExtensionValidator
from rest_framework import serializers
from .models import FeatureFlag, Notification, PlatformFile, ScheduledJob

#: Extensions the platform accepts (PLT-005). An allow-list rather than a
#: deny-list, because the failure mode of a deny-list is a format nobody thought
#: of — which is exactly the executable a hostile upload uses.
#:
#: This validates the *extension*, never the bytes: a renamed payload still
#: passes. The extension is a naming control, not a content control.
ALLOWED_FILE_EXTENSIONS = ["pdf", "png", "jpg", "csv", "json"]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = "__all__"
        # ``persisted`` and ``delivered`` are server-owned for the same reason
        # ``tenant_id`` is: a caller who could write them could mark an alert as
        # stored and received without either having happened (PLT-001).
        read_only_fields = [
            "id",
            "created_at",
            "tenant_id",
            "persisted",
            "delivered",
        ]


class FeatureFlagSerializer(serializers.ModelSerializer):
    """One feature switch, as the tenant's configuration API sees it (PLT-006).

    Only ``enabled`` and ``description`` are writable. ``tenant_id`` is
    server-owned, stamped from the resolved request; ``key`` is read-only because
    the resource is *addressed* by it and a body copy could disagree with the
    row's identity; ``id`` is server-generated and of no use to a caller that
    addresses flags by key.

    Listed rather than ``"__all__"``: a column added to the model later must not
    become a client-writable field here by default (AGENTS.md serializer rule).
    """

    class Meta:
        model = FeatureFlag
        fields = ["id", "tenant_id", "key", "enabled", "description"]
        read_only_fields = ["id", "tenant_id", "key"]


class PlatformFileSerializer(serializers.ModelSerializer):
    """A stored document, and the upload field that creates it (PLT-005).

    Every model field is read-only, and that is the design rather than a shortcut:
    the caller supplies the file and nothing else. A writable ``file_url`` would
    let them write a row pointing at a path of their choosing and a writable
    ``file_type`` would let them record a type the uploaded bytes never had.
    ``filename`` is excluded for a second reason: it is the sanitised original
    name, and the sanitisation has to happen on the server because the client's
    idea of a safe separator and this one's do not agree.

    ``file_url`` stays a :class:`~django.db.models.URLField` despite holding a
    relative path, and no model migration is needed for this endpoint; see the
    model docstring.
    """

    #: Write-only, because a field that echoed the file back would serve the
    #: document to anyone who can read the list.
    file = serializers.FileField(
        write_only=True,
        validators=[FileExtensionValidator(allowed_extensions=ALLOWED_FILE_EXTENSIONS)],
    )

    class Meta:
        model = PlatformFile
        # Listed rather than "__all__": a new column added to the shared model
        # later must not become a client-writable field here by default.
        fields = [
            "id",
            "file",
            "tenant_id",
            "uploaded_by",
            "filename",
            "file_type",
            "file_url",
            "uploaded_at",
        ]
        read_only_fields = [
            "id",
            "uploaded_at",
            "tenant_id",
            "uploaded_by",
            "filename",
            "file_type",
            "file_url",
        ]

    def validate_file(self, value):
        """Refuse an upload over ``settings.MAX_UPLOAD_MB`` (PLT-005).

        The cap belongs here rather than to Django's upload handlers, because
        theirs is a *memory* threshold: a file larger than
        ``FILE_UPLOAD_MAX_MEMORY_SIZE`` is streamed to a temporary file and
        accepted, so it never refuses anything. This is the first check that can
        say no, and it says no with the cap in the message.
        """
        limit = settings.MAX_UPLOAD_MB * 1024 * 1024
        if value.size > limit:
            raise serializers.ValidationError(
                f"Uploaded files are limited to {settings.MAX_UPLOAD_MB} MB.",
                code="max_size",
            )
        return value


class ScheduledJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduledJob
        fields = "__all__"
        read_only_fields = ["id", "tenant_id"]
