"""Platform views."""
import logging
import os
import re
import uuid as uuid_lib
from pathlib import Path

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.files.storage import default_storage
from django.http import FileResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import FeatureFlag, Notification, PlatformFile, ScheduledJob
from .permissions import PrivilegedWriteMixin
from .serializers import (
    FeatureFlagSerializer,
    NotificationSerializer,
    PlatformFileSerializer,
    ScheduledJobSerializer,
)

logger = logging.getLogger(__name__)

#: The shape a feature flag key may take (PLT-006). Enforced on the URL segment,
#: which this endpoint stores: the key becomes part of a feature-gate name in code
#: as well as part of a URL, so it is held to what both can carry. ``fullmatch``
#: anchors it at both ends and one case means the key in the URL, the key reaching
#: ``flag_enabled(...)`` and the key in the database are one string.
#:
#: ``.`` is deliberately **not** in this set. The router's detail route matches
#: with ``SimpleRouter._default_value_pattern`` (``[^/.]+``), so a dotted key 404s
#: at the pattern and never reaches :meth:`FeatureFlagViewSet._validated_key`.
#: Advertising a character the router cannot deliver is a contract no client can
#: satisfy, so namespacing is spelled with ``_``.
#:
#: Setting ``lookup_value_regex`` to this pattern instead was rejected: it turns
#: the 400 that names the broken rule into a bare 404 and leaves
#: ``_validated_key`` nothing to catch.
FLAG_KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")

#: Budget for the sanitised filename the platform stores (PLT-005).
#:
#: ``PlatformFile.file_url`` is a ``URLField`` of 200 characters and the stored
#: path is ``<tenant_id>/<upload uuid>/<filename>`` - 36 + 36 plus two separators,
#: so 73 columns are spent before the name starts. 80 is a *budget* and the name
#: out of it is at most 81: the truncation below caps the stem at
#: ``80 - len(extension)`` so the dot and extension survive. The longest stored
#: path is 155, measured, leaving 45 characters inside the column. Uncapped, the
#: *row* would fail to save after the file was written - the orphaned-file case.
#:
#: The cap is applied after sanitising, not before, so a traversal payload cannot
#: be rebuilt out of the bytes it leaves behind.
MAX_FILENAME_LENGTH = 80

#: Characters that are never allowed in a stored filename (PLT-005). Path
#: separators are the real danger: one turns ``MEDIA_ROOT/<tenant>/<uuid>/<name>``
#: into a path with a directory step the server did not choose. Null bytes and
#: control characters are stripped because they are how a name is made to *look*
#: harmless while still resolving differently. This is an enumeration and not the
#: whole answer: Unicode *format* characters such as the bidi override U+202E
#: cannot be listed, which is why :func:`_sanitise_filename` follows it with a
#: ``str.isprintable`` pass.
_FORBIDDEN_FILENAME_CHARS = str.maketrans("", "", "/\\\x00\r\n\t")


def _push_notification(tenant_id, payload):
    """Deliver a notification to the tenant's connected sockets (PLT-001, INT-012).

    The channel layer is async and the view is not, hence ``async_to_sync``.

    A push failure is logged and swallowed rather than raised: the row is already
    committed, so raising would answer 500 for a write that succeeded, the client
    would retry, and the alert would be duplicated - the worse failure for a
    clinical notification. A persisted-but-not-pushed row is still recoverable.
    """
    layer = get_channel_layer()
    if layer is None:
        logger.error(
            "notification push skipped: no channel layer is configured "
            "(CHANNEL_LAYERS)"
        )
        return
    try:
        async_to_sync(layer.group_send)(
            f"tenant_{tenant_id}",
            {"type": "send_notification", "payload": payload},
        )
    except Exception:
        logger.exception("notification push failed tenant_id=%s", tenant_id)


def _sanitise_filename(raw_name: str) -> str:
    """Reduce a client-supplied filename to a single safe path component.

    The client's filename is untrusted input that ends up as a path component, so
    it is reduced to one component: no separators, no parent references, no
    control characters, short enough that the row storing it cannot fail. The
    extension survives the truncation because ``file_type`` is derived from this
    same string - a filename whose extension was cut away would record a type the
    validation never saw.

    Deliberately *not* rejected for being hostile: ``../../etc/passwd`` is stored
    as ``etcpasswd``, indistinguishable from a tidy-but-unusual legitimate name.
    Refusing would tell the sender the path was interesting.
    """
    # ``..`` first, then separators: removing separators first would join what
    # is left of ``..`` to the next component and leave ``...`` behind, which
    # still normalises away from its own directory on some filesystems.
    candidate = raw_name.replace("..", "").translate(_FORBIDDEN_FILENAME_CHARS)
    # Then everything the Unicode categories call "Other" or "Separator". The
    # reason this pass exists and is not left to Django's multipart parser is
    # *format* characters: a bidi override is invisible in the download's
    # ``Content-Disposition`` and reorders the name in a save dialog, so a
    # document called ``report.exe.pdf`` is what the user is shown.
    candidate = "".join(character for character in candidate if character.isprintable())
    # Strip a trailing dot or space, which Windows treats as part of the name.
    candidate = candidate.strip().rstrip(".")

    # The extension is taken *after* sanitising, so a name like ``x.pdf/../../y``
    # cannot fake one, and is kept separately so the cap applies to the stem alone.
    stem, _, extension = candidate.rpartition(".")
    if not stem:
        # A name that is only an extension (``.pdf``) has nothing to truncate.
        stem, extension = candidate, ""

    stem = stem.strip()[: MAX_FILENAME_LENGTH - len(extension)]
    if not stem:
        # Unreachable in practice: an empty filename would leave the row's
        # ``filename`` column blank, so it is asserted rather than trusted.
        stem = "upload"
    return f"{stem}.{extension}" if extension else stem


def _uploaded_by(request):
    """The authenticated principal's pk, coerced for a ``UUIDField`` column.

    The column is a UUIDField but ``User.pk`` is an integer, and the audit chain
    already learned this the hard way: writing the raw int stores one value and
    reading the row back gives another, so no write can verify against its own
    replica. The field's own ``to_python`` is the conversion ``save()`` would
    apply anyway, applied at the point the value enters.
    """
    user = request.user
    if user is None or not getattr(user, "is_authenticated", False):
        # Unreachable through the API, but a caller reaching here without a
        # principal would otherwise write ``uploaded_by = NULL`` silently.
        raise PermissionDenied("An authenticated user must upload the file.")
    return PlatformFile._meta.get_field("uploaded_by").to_python(user.pk)


def _relative_upload_path(tenant_id, raw_name: str) -> tuple[str, str, str]:
    """Build the storage path for one upload.

    Returns ``(relative_path, sanitised_filename, extension)``.

    The tenant directory is the storage half of tenant isolation: even if a row
    were read across tenants, the bytes are partitioned by hospital. The upload
    uuid directory stops two same-named files from one tenant colliding, and is
    generated server-side so the client has no say in it.

    The tenant id is normalised through ``uuid.UUID`` *here*, once. The download
    compares the stored path's first component against ``str(row.tenant_id)`` -
    the canonical form a ``UUIDField`` reads back - so an id sent in any other
    representation (``uuid4().hex``, uppercase) would produce a row whose own
    document the owner can never fetch: upload 201, download 404, with nothing
    wrong the caller could report. That matters more on a case-insensitive
    filesystem, where two spellings of one id are one directory.

    A value the column would reject anyway raises here, before anything is
    written: the response is a 500 either way, but no bytes reach storage and no
    orphan-delete runs for them.
    """
    sanitised = _sanitise_filename(raw_name)
    # The extension comes from the sanitised name *after* the allow-list
    # validated the original, so ``file_type`` records what was accepted.
    _, extension = os.path.splitext(sanitised)
    file_type = extension.lstrip(".").lower()
    relative = f"{uuid_lib.UUID(str(tenant_id))}/{uuid_lib.uuid4()}/{sanitised}"
    return relative, sanitised, file_type


def _store_upload(relative_path: str, uploaded) -> str:
    """Write the uploaded chunk to storage under ``MEDIA_ROOT``; return the name.

    ``FileSystemStorage`` creates the parent directories, so they come into
    existence with the file rather than needing to be made first - a separate
    creation could succeed while the write failed and leave an empty tenant
    directory behind. ``save()`` returns the name it *actually* used, which a
    backend may have renamed on collision; the row records that, because a row
    naming a path nothing was written to is a 404 the owner cannot explain.
    """
    return default_storage.save(relative_path, uploaded)


def _upload_directory_id(relative_path: str) -> str:
    """The per-upload uuid directory of a stored path, or ``"-"``.

    Derived from the path because storage may report back a name other than the
    requested one, and this is the directory the *stored* file landed in - the
    one an operator has to look for. The ``"-"`` fallback exists so an
    unexpected path cannot be leaked through the log line that keeps it out of
    the logs.
    """
    parts = relative_path.split("/")
    return parts[1] if len(parts) > 2 else "-"


def _discard_upload(relative_path: str, tenant_id) -> None:
    """Delete a stored file whose row failed to land.

    The write is ordered file-then-row, so a failure between the two leaves a
    document nobody owns: readable by no view, counted by no quota, invisible to
    any cleanup that works from the table.

    Logged by tenant and upload directory, never by path: a document is routinely
    named after the patient it concerns, and this line runs unattended on the
    failure path into whatever log aggregation ships next. The tenant and uuid
    are what an operator needs to find the file on disk.

    ``exc_info`` is deliberately *not* attached, hence ``logger.error`` over
    ``logger.exception``: the ``OSError`` carries the absolute path in its own
    message, so the traceback would restore the filename the format string just
    removed. Class and ``errno`` are logged instead.
    """
    try:
        default_storage.delete(relative_path)
    except OSError as exc:
        # Logged, not raised: the caller is already unwinding from the failure
        # that stranded the file, and a second exception would replace the
        # response with a 500 that hides the original cause.
        logger.error(
            "could not delete stranded upload tenant_id=%s upload_uuid=%s "
            "error=%s errno=%s",
            tenant_id,
            _upload_directory_id(relative_path),
            type(exc).__name__,
            exc.errno,
        )


def _resolve_download_path(platform_file: PlatformFile) -> Path:
    """Resolve a row's stored path, refusing anything outside its own tenant.

    Defence in depth, labelled as such: the upload path cannot produce a
    traversal (the filename is sanitised, the uuid directory server-generated),
    so this exists for a row written by some other route - a data migration, an
    operator's SQL, a future bug - which would otherwise be served. 404 rather
    than 400 keeps the refusal indistinguishable from the row not existing.

    The row is the argument rather than its ``file_url`` because the check has
    two halves and only the row carries both. Containment under ``MEDIA_ROOT``
    proves the path is somewhere the server chose to store files; it says nothing
    about *whose* directory that is. A row owned by one tenant whose stored path
    points into another tenant's tree - written the same way, by a route the API
    does not expose - passes containment and streams the wrong hospital's
    document, which is the one failure this function is named for. Hence the
    tenant id is compared against the stored path's own first component, and a
    bare ``file_url`` string is deliberately not accepted: a tenant parsed out of
    the path by the caller and compared against the same path is a check that
    cannot fail.
    """
    relative_path = platform_file.file_url or ""
    if relative_path.split("/", 1)[0] != str(platform_file.tenant_id):
        # Not an OSError/ValueError case, so it is raised rather than caught
        # below: it is a refusal, not a resolution failure, and it must not be
        # reported as one. 404 for the same reason - a mismatched row must be
        # indistinguishable from a row that does not exist.
        raise NotFound("The requested file is not available.")
    media_root = Path(default_storage.location).resolve()
    try:
        resolved = (media_root / relative_path).resolve()
        # ``is_relative_to`` is what makes this a containment check rather than
        # a string prefix: ``/srv/media-evil`` shares a prefix with
        # ``/srv/media`` and is not inside it.
        resolved.relative_to(media_root)
    except (OSError, ValueError) as exc:
        raise NotFound("The requested file is not available.") from exc
    if not resolved.is_file():
        raise NotFound("The requested file is not available.")
    return resolved


class NotificationViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """In-app notifications (PLT-001)."""
    serializer_class = NotificationSerializer
    queryset = Notification.objects.all()

    def perform_create(self, serializer):
        """Persist the notification, then push it to the tenant's sockets.

        ``persisted`` is stamped here, never taken from the client: a create
        through this API is by definition an in-app notification, so it has to
        survive a reload. The push is what makes the consumer's ``delivered``
        flag mean anything - before it existed no socket ever heard about a row,
        so nothing could ever set the flag.
        """
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        notification = serializer.save(**{"tenant_id": tenant_id, "persisted": True})
        _push_notification(str(tenant_id), NotificationSerializer(notification).data)

    @action(detail=False, methods=["get"])
    def unread(self, request):
        """List unread notifications."""
        queryset = self.get_queryset().filter(read_at__isnull=True)
        return Response(NotificationSerializer(queryset, many=True).data)

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Mark a notification as read."""
        notification = self.get_object()
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
        return Response(NotificationSerializer(notification).data)


class FeatureFlagViewSet(
    PrivilegedWriteMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet
):
    """Per-tenant feature switches (PLT-006).

    ``GET`` lists the tenant's flags to any authenticated member of it; ``PUT``
    (or ``PATCH``) on ``/api/v1/feature-flags/{key}/`` sets one. That is the whole
    write surface: the key is the URL segment (``lookup_field``), the tenant is
    the request's, and the row is created when it does not exist yet.

    **PUT upserts, which is why POST is not routed** - a flag must be settable
    before it exists - and it answers 200 either way, so repeating the request is
    idempotent in status as well as in effect. DELETE is not routed either:
    removing the row would leave the feature reading as off by absence while
    erasing the record that anyone decided it. Switching a feature off is a PUT of
    ``enabled: false``. ``PATCH`` is the same call with a partial body.

    Writes require a privileged membership in the request's tenant
    (``IsPrivilegedTenantMember``); reads do not, because the client needs the
    configuration to render the right screens whether or not it may change it.
    """

    serializer_class = FeatureFlagSerializer
    #: The URL segment is the flag's key, not its primary key. Tenant scoping still
    #: comes from the mixin's queryset - which is what makes a cross-tenant key
    #: answer 404 rather than naming a row that exists.
    lookup_field = "key"
    #: Ordered so the list is deterministic; see PlatformFileViewSet.
    queryset = FeatureFlag.objects.order_by("key")
    http_method_names = ["get", "put", "patch", "head", "options"]

    def update(self, request, *args, **kwargs):
        """Set the named flag, creating it for this tenant if it is new.

        DRF's ``UpdateModelMixin.update`` resolves through ``get_object()`` and
        404s when there is none - right for every other viewset here, wrong for
        this one, because the flag a hospital is turning on does not exist yet.
        The create branch therefore runs the *same* validation and the *same*
        ``perform_create`` the mixin would have run, keeping the tenant stamp and
        the audit event (AUD-001) identical to every other tenant-owned write.

        The lookup goes through ``self.get_queryset()``, the mixin's tenant-scoped
        queryset, not the model manager: a lookup that dropped the tenant filter
        would overwrite another hospital's row and still answer 200.
        """
        partial = kwargs.pop("partial", False)
        key = self._validated_key(request)
        instance = self.get_queryset().filter(key=key).first()

        if instance is None:
            serializer = self.get_serializer(data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            return Response(serializer.data)

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def perform_create(self, serializer):
        """Stamp the key from the URL alongside the mixin's tenant and audit.

        ``key`` is read-only in the serializer because the URL is where it comes
        from, which on this create path leaves it with nowhere to come from - so
        it is injected here rather than by making the field writable and asking
        every caller to keep a body value in step with the path. It is the value
        ``update`` looked the row up by, validated the same way.
        """
        serializer.validated_data[self.lookup_field] = self._validated_key(
            self.request
        )
        super().perform_create(serializer)

    def _validated_key(self, request) -> str:
        """The flag key from the URL, or a 400 naming why it is unusable.

        The one write on the endpoint no client-side validation reaches: the
        router hands the viewset whatever the path segment spelled, and this
        endpoint stores it. See :data:`FLAG_KEY_PATTERN` for the shape.

        Refused with a validation error rather than 404 because the key is
        present and the *request* is what is wrong with it. The router's own
        pattern is the wider ``[^/.]+``, so it admits segments this endpoint will
        not store - an uppercase key, an over-long one, a quote - and those are
        answered here with the rule they broke. What the URL cannot express at
        all is a 404 that never arrives, and no row is written either way.
        """
        key = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field, "")
        if not isinstance(key, str) or not FLAG_KEY_PATTERN.fullmatch(key):
            raise ValidationError(
                {
                    self.lookup_field: (
                        "A feature flag key may contain only lowercase letters, "
                        "digits, '_' and '-', must start with a letter or "
                        "digit, and may be at most 64 characters."
                    )
                }
            )
        return key


class PlatformFileViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """File storage with access control (PLT-005).

    Uploads arrive as multipart on the standard create route and are answered
    201; downloads are a detail action that streams the stored bytes back to the
    owning tenant and nobody else.
    """
    serializer_class = PlatformFileSerializer
    # Ordered so the paginated list is deterministic. An unordered queryset is not
    # just untidy: page 2 of an unordered result can repeat or skip rows, so a
    # document list a hospital pages through can silently drop one. On the queryset
    # rather than ``Meta.ordering`` to keep the route from needing a migration.
    queryset = PlatformFile.objects.order_by("-uploaded_at")

    #: Multipart first, then JSON and form for the ordinary verbs. Scoped to this
    #: viewset rather than the project default so the notification endpoints do
    #: not change behaviour as a side effect.
    parser_classes = [MultiPartParser, JSONParser, FormParser]

    #: A stored document is written once and never mutated through the API.
    #: DELETE would remove the row and leave the bytes on disk with nothing
    #: referencing them - the orphan the failed-write path below deletes, reached
    #: deliberately. PUT has no writable field and 400s; PATCH likewise but answers
    #: 200, which is worse because the caller is told the document was updated when
    #: nothing changed. Retention and destruction are governed by the audit policy
    #: (AUD-004), not by a DELETE verb on a storage route.
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        """Store the document, then write the row that references it.

        The order is deliberate: the file first, because its storage path is an
        input to the row; the row second, because a row pointing at a file that
        was never stored is a dangling reference that only surfaces on download.

        Nothing here reads a value the client supplied for the row. ``tenant_id``
        comes from the mixin's stamp, ``uploaded_by`` from the authenticated
        principal, and ``filename``/``file_type``/``file_url`` from the sanitised
        upload - the serializer marks all of them read-only, so a caller who tries
        to supply any of them is ignored rather than obeyed.
        """
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")

        uploaded = serializer.validated_data.get("file")
        if uploaded is None:
            # Unreachable through the API, but ``perform_create`` must never write
            # a row with no document behind it.
            raise NotFound("A file must be uploaded with the request.")

        relative_path, sanitised, file_type = _relative_upload_path(
            str(tenant_id), uploaded.name
        )
        stored_path = _store_upload(relative_path, uploaded)

        try:
            # ``file`` is popped: the row is written through the model manager,
            # which takes field names only, and an ``UploadedFile`` is not a column.
            serializer.validated_data.pop("file", None)
            serializer.save(
                tenant_id=tenant_id,
                uploaded_by=_uploaded_by(self.request),
                filename=sanitised,
                file_type=file_type,
                file_url=stored_path,
            )
        except Exception:
            # The name the storage reported, not the one that was requested:
            # deleting the requested name would leave the renamed file behind,
            # which is the orphan this is here to prevent.
            _discard_upload(stored_path, tenant_id)
            raise

        # Audit event (AUD-001), as the mixin does for every other tenant-owned
        # write. The file row is logged by id, never by name or content - a
        # document named after a patient is what a log line must not reproduce.
        self._write_audit_log(serializer.instance, "create")

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Stream the stored document back to its owning tenant (PLT-005).

        ``self.get_object()`` runs the tenant-scoped queryset first, so another
        hospital's row 404s here rather than leaking - the caller cannot tell "not
        yours" from "not there", which is the whole protection: a 403 would
        confirm the row exists.

        Served from this view, never from ``django.views.static.serve``, which is
        documented as unsuitable for production and answers from the filesystem
        with no permission check at all. Serving through the view is what puts
        authentication, the tenant filter and both path checks in front of the
        bytes.
        """
        platform_file = self.get_object()
        path = _resolve_download_path(platform_file)

        # ``as_attachment`` sets Content-Disposition with the *original* filename,
        # so the response names the document rather than the storage path - which
        # would reveal the tenant id and the per-upload uuid.
        response = FileResponse(
            path.open("rb"), as_attachment=True, filename=platform_file.filename
        )
        # Identifier only: no filename, no byte count that would hint at content.
        logger.info(
            "file download file_id=%s tenant_id=%s",
            platform_file.id,
            platform_file.tenant_id,
        )
        return response


class ScheduledJobViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """Background job visibility (PLT-004), scoped to the request's tenant (TEN-002)."""
    serializer_class = ScheduledJobSerializer
    queryset = ScheduledJob.objects.all()
