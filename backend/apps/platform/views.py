"""Platform views."""
import logging
import os
import uuid as uuid_lib
from pathlib import Path

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.http import FileResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import Notification, PlatformFile, ScheduledJob
from .serializers import NotificationSerializer, PlatformFileSerializer, ScheduledJobSerializer

logger = logging.getLogger(__name__)

#: Longest sanitised original filename the platform stores (PLT-005).
#:
#: The cap exists because ``PlatformFile.file_url`` is a ``URLField`` whose
#: column is 200 characters, and the stored path is
#: ``<tenant_id>/<upload uuid>/<filename>``. A tenant id is 36 characters, an
#: upload uuid is 36, and they take two separators, so the filename is capped at
#: 80 to leave room - if it were not, the *row* would fail to save after the
#: file had already been written, which is the orphaned-file case this comment
#: is here to prevent. The cap is applied after sanitising, not before, so a
#: traversal payload cannot be rebuilt out of the bytes it leaves behind.
MAX_FILENAME_LENGTH = 80

#: Characters that are never allowed in a stored filename (PLT-005).
#:
#: Path separators are the actual danger: a name containing one turns
#: ``MEDIA_ROOT/<tenant>/<uuid>/<name>`` into a path with an extra directory
#: step the server did not choose. Null bytes and control characters are
#: stripped because they are how a name is made to *look* harmless to a
#: validator while still resolving differently, and because they make a row
#: impossible to display. ``..`` is removed as a literal, for the same reason.
_FORBIDDEN_FILENAME_CHARS = str.maketrans("", "", "/\\\x00\r\n\t")


def _push_notification(tenant_id, payload):
    """Deliver a notification to the tenant's connected sockets (PLT-001, INT-012).

    The channel layer is async and the view is not, hence ``async_to_sync``.

    A push failure is logged and swallowed rather than raised. The row is already
    committed by the time this runs, so an exception here would answer 500 for a
    write that actually succeeded - the client, seeing an error, retries and the
    alert is duplicated, which is the worse failure for a clinical notification.
    A persisted-but-not-pushed row is still recoverable: the client polls on
    reload, and the row's ``delivered`` flag records what never went out.
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

    The client's filename is untrusted input that ends up as a path component,
    so it is reduced to what it is allowed to be: one component, no separators,
    no parent references, no control characters, and short enough that the row
    storing it cannot fail.

    The extension is preserved through the truncation rather than cut off with
    the rest, because ``file_type`` is derived from this same string and a
    filename whose extension was truncated away would record a type the
    validation never actually saw.

    Note what is deliberately *not* done here: the name is not rejected for
    being hostile. An attacker who sends ``../../etc/passwd`` gets a stored
    file called ``etcpasswd``, which is indistinguishable from a legitimate
    upload having tidy-but-unusual naming. Refusing the request would tell them
    the path was interesting; storing it renamed tells them nothing.
    """
    # ``..`` first, then separators: removing separators first would join what
    # is left of ``..`` to the next component and leave ``...`` behind, which
    # still normalises away from its own directory on some filesystems.
    candidate = raw_name.replace("..", "").translate(_FORBIDDEN_FILENAME_CHARS)
    # Strip a trailing dot or space, which Windows treats as part of the name
    # and other systems do not.
    candidate = candidate.strip().rstrip(".")

    # The extension is kept separately so the cap below is applied to the stem
    # alone. It is taken *after* sanitising, so a name like ``x.pdf/../../y``
    # cannot fake one.
    stem, _, extension = candidate.rpartition(".")
    if not stem:
        # A name that is only an extension (``.pdf``) has nothing to truncate.
        stem, extension = candidate, ""

    stem = stem.strip()[: MAX_FILENAME_LENGTH - len(extension)]
    if not stem:
        # Only reachable if every character was removed. A name that survives
        # sanitising as nothing still has to arrive here *after* the extension
        # check (which runs on the original name), so this is unreachable in
        # practice - asserted rather than trusted, because an empty filename
        # would leave the row's ``filename`` column blank.
        stem = "upload"
    return f"{stem}.{extension}" if extension else stem


def _uploaded_by(request):
    """The authenticated principal's pk, coerced for a ``UUIDField`` column.

    The column is a UUIDField but ``User.pk`` is an integer, and the audit chain
    already learned this lesson the hard way: writing the raw int stores one
    value and reading the row back gives another, so no write can ever verify
    against its own replica. The model field's own ``to_python`` is the
    conversion ``save()`` would apply anyway, so this is not a second mechanism
    - it is the one Django uses, applied at the point the value enters.
    """
    user = request.user
    if user is None or not getattr(user, "is_authenticated", False):
        # Unreachable through the API - every route on this viewset is
        # IsAuthenticated - but a caller that reaches here without a principal
        # would otherwise write ``uploaded_by = NULL`` silently.
        raise PermissionDenied("An authenticated user must upload the file.")
    return PlatformFile._meta.get_field("uploaded_by").to_python(user.pk)


def _relative_upload_path(tenant_id, raw_name: str) -> tuple[str, str, str]:
    """Build the storage path for one upload.

    Returns ``(relative_path, sanitised_filename, extension)``.

    The tenant directory is the storage half of tenant isolation: even if a row
    were somehow read across tenants, the bytes are partitioned by hospital.
    The upload uuid directory is what stops two same-named files from one
    tenant colliding, and it is generated server-side precisely so the client
    has no say in it.
    """
    sanitised = _sanitise_filename(raw_name)
    # The extension is taken from the sanitised name after the allow-list has
    # validated the original, so ``file_type`` records the extension that was
    # actually accepted rather than the one the client claimed.
    _, extension = os.path.splitext(sanitised)
    file_type = extension.lstrip(".").lower()
    relative = f"{tenant_id}/{uuid_lib.uuid4()}/{sanitised}"
    return relative, sanitised, file_type


def _store_upload(relative_path: str, uploaded) -> str:
    """Write the uploaded chunk to storage under ``MEDIA_ROOT``; return the name.

    Django's ``FileSystemStorage`` creates the parent directories, so the tenant
    and per-upload directories come into existence with the file rather than
    needing to be made first - a directory creation that ran separately could
    succeed while the write failed and leave an empty tenant directory behind.

    ``save()`` returns the name it *actually* used, which is not necessarily the
    one it was given: a storage backend may rename on collision or sanitise. The
    row records the returned name rather than the requested one, because a row
    naming a path nothing was written to is a 404 the owner cannot explain.
    """
    return default_storage.save(relative_path, uploaded)


def _discard_upload(relative_path: str) -> None:
    """Delete a stored file whose row failed to land.

    The write is ordered file-then-row, so a failure between the two leaves a
    document nobody owns: readable by no view, counted by no quota, and
    invisible to any cleanup that works from the table. Deleting it here keeps
    storage and rows agreeing.
    """
    try:
        default_storage.delete(relative_path)
    except OSError:
        # Logged, not raised: the caller is already unwinding from the failure
        # that stranded the file, and a second exception would replace the
        # response with a 500 that hides the original cause.
        logger.exception("could not delete stranded upload path=%s", relative_path)


def _resolve_download_path(relative_path: str) -> Path:
    """Resolve a row's stored path, refusing anything outside ``MEDIA_ROOT``.

    Defence in depth, and labelled as such: the upload path cannot produce a
    traversal because the filename is sanitised and the uuid directory is
    server-generated, so this check exists for the case where a row was written
    by some other route - a data migration, an operator's SQL, a future bug -
    and would otherwise be served. Returning 404 rather than 400 keeps the
    refusal indistinguishable from the row not existing.
    """
    media_root = Path(default_storage.location).resolve()
    try:
        resolved = (media_root / relative_path).resolve()
        # ``is_relative_to`` is what makes this a containment check rather than
        # a string prefix: ``/srv/media-evil`` shares a prefix with
        # ``/srv/media`` and is not inside it.
        resolved.relative_to(media_root)
    except (OSError, ValueError, SuspiciousFileOperation) as exc:
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


class PlatformFileViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """File storage with access control (PLT-005).

    Uploads arrive as multipart on the standard create route and are answered
    201; downloads are a detail action that streams the stored bytes back to the
    owning tenant and nobody else.
    """
    serializer_class = PlatformFileSerializer
    # Ordered so the paginated list is deterministic. An unordered queryset is
    # not just untidy: page 2 of an unordered result set can repeat or skip
    # rows, so a document list a hospital pages through can silently drop one.
    # Done on the queryset rather than the model's ``Meta.ordering`` to keep
    # the route from needing a migration.
    queryset = PlatformFile.objects.order_by("-uploaded_at")

    #: Multipart first so a file upload is parsed as a form, then JSON and form
    #: for the ordinary verbs. ``NotificationViewSet`` in this same file keeps
    #: its own parser list untouched: scoping this to ``PlatformFileViewSet``
    #: rather than to the project default is what stops the notification
    #: endpoints from changing behaviour as a side effect of this task.
    parser_classes = [MultiPartParser, JSONParser, FormParser]

    #: A stored document is written once and never mutated through the API.
    #:
    #: DELETE would remove the row and leave the bytes on disk with nothing
    #: referencing them - the orphan the failed-write path below deletes, reached
    #: deliberately. PUT has no writable field and 400s; PATCH has no writable
    #: field either but answers 200, which is the worse of the two because the
    #: caller is told the document was updated when nothing changed. Retention
    #: and destruction are governed by the audit policy (AUD-004), not by a
    #: DELETE verb on a storage route.
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        """Store the document, then write the row that references it.

        The order is deliberate. The file is written first because its storage
        path is an input to the row, not the other way round; the row is written
        second because a row pointing at a file that was never stored is a
        dangling reference that only surfaces when someone tries to download it.

        Nothing here reads a value the client supplied for the row. ``tenant_id``
        comes from the mixin's stamp, ``uploaded_by`` from the authenticated
        principal, and ``filename``/``file_type``/``file_url`` from the
        sanitised upload - the serializer marks all of them read-only, so a
        caller who tries to supply any of them is ignored rather than obeyed.
        """
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")

        uploaded = serializer.validated_data.get("file")
        if uploaded is None:
            # ``file`` is the serializer's only writable field, so this is
            # unreachable through the API. Asserted anyway: ``perform_create``
            # must never write a row with no document behind it.
            raise NotFound("A file must be uploaded with the request.")

        relative_path, sanitised, file_type = _relative_upload_path(
            str(tenant_id), uploaded.name
        )
        stored_path = _store_upload(relative_path, uploaded)

        try:
            # ``file`` is popped rather than left in place because the row is
            # written through the model manager, which takes field names only -
            # an ``UploadedFile`` is not a column, and leaving it would raise
            # after the bytes were already stored.
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
            _discard_upload(stored_path)
            raise

        # Write an audit trail event (AUD-001), the same way the mixin does for
        # every other tenant-owned write. The file row is logged by id, never by
        # name or content - a document named after a patient is exactly what a
        # log line must not reproduce.
        self._write_audit_log(serializer.instance, "create")

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Stream the stored document back to its owning tenant (PLT-005).

        ``self.get_object()`` runs the tenant-scoped queryset first, so a row
        belonging to another hospital 404s here rather than leaking - the caller
        cannot tell "not yours" from "not there", which is the whole protection:
        a 403 would confirm the row exists.

        Served from this view, never from ``django.views.static.serve``: that
        helper is documented as unsuitable for production and answers from the
        filesystem with no permission check whatsoever, so it would hand any
        document to any caller who guessed its path. Serving through the view
        is what puts authentication, the tenant filter and the path containment
        check in front of the bytes.
        """
        platform_file = self.get_object()
        path = _resolve_download_path(platform_file.file_url)

        # ``as_attachment`` sets Content-Disposition with the *original*
        # filename, so the response names the document the uploader chose
        # rather than the storage path - the path reveals the tenant id and the
        # per-upload uuid, neither of which is any of the caller's business.
        response = FileResponse(
            path.open("rb"), as_attachment=True, filename=platform_file.filename
        )
        # Log the identifier and nothing else: no filename, no byte count that
        # would hint at the document's content.
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
