"""Platform serializers."""
from django.conf import settings
from django.core.validators import FileExtensionValidator
from rest_framework import serializers
from .models import FeatureFlag, Notification, PlatformFile, ScheduledJob

#: Extensions the platform accepts (PLT-005).
#:
#: An allow-list rather than a deny-list, because the failure mode of a
#: deny-list is a format nobody thought of - which is exactly the executable a
#: hostile upload uses. The list is documents only: a PDF report, a PNG or JPG
#: image, a CSV export, a JSON payload.
#:
#: This validates the *extension*, never the bytes. Pillow is a declared
#: dependency of this project for another feature and is deliberately not
#: imported here, so content sniffing is not claimed and does not happen: a
#: renamed payload still passes. Django's own warning applies - the extension
#: is a naming control, not a content control - and the endpoint does not claim
#: otherwise.
ALLOWED_FILE_EXTENSIONS = ["pdf", "png", "jpg", "csv", "json"]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = "__all__"
        # ``persisted`` and ``delivered`` are server-owned and belong in
        # read_only_fields for the same reason ``tenant_id`` does: a caller who
        # could write them could mark an alert as stored and received without
        # either having happened - the view persists what it creates and the
        # WebSocket consumer sets delivered when a socket actually receives the
        # row (PLT-001).
        read_only_fields = [
            "id",
            "created_at",
            "tenant_id",
            "persisted",
            "delivered",
        ]


class FeatureFlagSerializer(serializers.ModelSerializer):
    """One feature switch, as the tenant's configuration API sees it (PLT-006).

    Only ``enabled`` and ``description`` are writable, and both are the caller's
    to choose. The other three are read-only for specific reasons:

    ``tenant_id``
        Server-owned. ``TenantScopedQuerysetMixin.perform_create`` stamps it from
        the resolved request; a writable one would be a required input that every
        caller answers from a header it chose (see the mixin's own note).
    ``key``
        Taken from the URL - the resource is *addressed* by its key. Echoing a
        second copy in the body would add one more spelling of the same name to
        keep in step, and the one that could disagree with the row's identity.
    ``id``
        Server-generated, and of no use to a caller that addresses flags by key.

    Listed rather than ``"__all__"``: a column added to the model later must not
    become a client-writable field here by default (AGENTS.md serializer rule).
    """

    class Meta:
        model = FeatureFlag
        fields = ["id", "tenant_id", "key", "enabled", "description"]
        read_only_fields = ["id", "tenant_id", "key"]


class PlatformFileSerializer(serializers.ModelSerializer):
    """A stored document, and the upload field that creates it (PLT-005).

    Every model field is read-only, and that is the design rather than a
    shortcut: the caller supplies the file and nothing else. The stored
    filename, the recorded type, the storage path and the owner are all
    derived from validated input plus the request, so a writable ``file_url``
    would let a caller write a row pointing at a path of their choosing and a
    writable ``file_type`` would let them record a type the uploaded bytes
    never had. ``filename`` is excluded for a second reason: it is the
    sanitised original name, and the sanitisation has to happen on the server
    because the client's idea of a safe separator and this one's do not agree.

    ``file_url`` stays a :class:`~django.db.models.URLField` despite holding a
    relative path. A relative path cannot pass ``URLField``'s application-level
    validators through a serializer, while the ORM's ``create()`` runs no model
    validators - so the value is written server-side after validation and the
    model keeps the field, and its 200-character column, exactly as they are.
    No model migration is needed for this endpoint; see the model docstring.
    """

    #: The uploaded document. Write-only, because a field that echoed the file
    #: back would serve the document to anyone who can read the list.
    file = serializers.FileField(
        write_only=True,
        validators=[FileExtensionValidator(allowed_extensions=ALLOWED_FILE_EXTENSIONS)],
    )

    class Meta:
        model = PlatformFile
        # Listed rather than "__all__": the model is shared with rows an
        # administrator may write directly, and a new column added to it later
        # must not become a client-writable field here by default.
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
        accepted, so it never refuses anything. This is the first check that
        can say no, and it says no with the cap in the message so the caller
        learns the limit rather than being handed a bare 400.
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
