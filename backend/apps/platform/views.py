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

#: The shape a feature flag key may take (PLT-006).
#:
#: Enforced on the URL segment, which this endpoint stores: the key becomes part
#: of a feature-gate name in code as well as part of a URL, so it is held to what
#: both can carry. Matched with ``fullmatch``, so it is anchored at both ends, and
#: restricted to one case, so the key that arrives in a URL, the key that reaches a
#: ``flag_enabled(...)`` call and the key in the database are one string rather
#: than three spellings of it.
#:
#: ``.`` is deliberately **not** in this character set. The router's detail route
#: matches its lookup with ``SimpleRouter._default_value_pattern`` - ``[^/.]+`` -
#: so a key carrying a dot does not match the URL at all: it 404s at the pattern,
#: never reaches :meth:`FeatureFlagViewSet._validated_key`, and is refused before
#: any code in this project sees it. Advertising a character the router cannot
#: deliver is a contract no client can satisfy, so namespacing is spelled with
#: ``_`` (``abdm_linkage``) and the advertised set is the routable one.
#:
#: The alternative - setting ``lookup_value_regex`` on the viewset to this same
#: pattern, which ``SimpleRouter.get_lookup_regex`` prefers over its default -
#: was rejected: it makes the router reject a key the application would have
#: explained, turning a 400 that names the rule ("lowercase letters, digits,
#: '_' and '-'") into a bare 404, and it leaves ``_validated_key`` with nothing
#: left to catch on the URL path. Two layers is the arrangement worth keeping:
#: the router accepts a segment, and this endpoint refuses the ones it will not
#: store and says which rule they broke.
FLAG_KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")

#: Budget for the sanitised filename the platform stores (PLT-005).
#:
#: The cap exists because ``PlatformFile.file_url`` is a ``URLField`` whose
#: column is 200 characters, and the stored path is
#: ``<tenant_id>/<upload uuid>/<filename>``. A tenant id is 36 characters and an
#: upload uuid is 36, and the two take a separator each, so 73 characters of the
#: column are spoken for before the name starts.
#:
#: 80 is a *budget*, and the name that comes out of it is at most 81 characters:
#: the truncation below caps the stem at ``80 - len(extension)`` so the dot and
#: the extension survive, and they are then added on top. The longest stored
#: path is therefore 36 + 1 + 36 + 1 + 81 = 155, not 154 - measured, and 45
#: characters inside the column. If the cap were not applied, the *row* would
#: fail to save after the file had already been written, which is the
#: orphaned-file case this comment is here to prevent.
#:
#: The cap is applied after sanitising, not before, so a traversal payload
#: cannot be rebuilt out of the bytes it leaves behind.
MAX_FILENAME_LENGTH = 80

#: Characters that are never allowed in a stored filename (PLT-005).
#:
#: Path separators are the actual danger: a name containing one turns
#: ``MEDIA_ROOT/<tenant>/<uuid>/<name>`` into a path with an extra directory
#: step the server did not choose. Null bytes and control characters are
#: stripped because they are how a name is made to *look* harmless to a
#: validator while still resolving differently, and because they make a row
#: impossible to display. ``..`` is removed as a literal, for the same reason.
#:
#: This is an enumeration and it is not the whole answer: Unicode *format*
#: characters such as the bidi override U+202E cannot be listed, which is why
#: :func:`_sanitise_filename` follows it with a ``str.isprintable`` pass.
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
    # Then everything the Unicode categories call "Other" or "Separator":
    # ``isprintable`` rejects control characters, unassigned code points and -
    # the reason this pass exists - *format* characters. A bidi override is
    # invisible in the download's ``Content-Disposition`` and reorders how the
    # name reads in a save dialog, so a document called ``report.exe.pdf`` is
    # what the user is shown. They cannot be enumerated the way ``\r\n`` can,
    # and Django's own multipart parser runs this same filter - repeating it
    # here means this function is the control on its own account rather than
    # one that happens to sit behind another one.
    candidate = "".join(character for character in candidate if character.isprintable())
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

    The tenant id is normalised through ``uuid.UUID`` *here*, once, so the
    directory is named by the id rather than by the spelling that arrived. The
    download compares the stored path's first component against
    ``str(row.tenant_id)`` - the canonical form a ``UUIDField`` reads back - so
    a header sent in any other representation (``uuid4().hex``, uppercase)
    would otherwise produce a row whose own document the owner can never fetch:
    upload 201, download 404, with nothing wrong the caller could report.
    Normalising at the write keeps that check a plain string comparison, which
    cannot itself raise on a malformed path, and it leaves the directory name
    equal to the tenant's real id rather than one of several spellings of it -
    which matters on a case-insensitive filesystem, where two spellings of one
    id are one directory and two tenants must not be.

    A value the column would reject anyway raises here, before anything is
    written, instead of after: the response is a 500 either way, but no bytes
    reach storage and no orphan-delete runs for them.
    """
    sanitised = _sanitise_filename(raw_name)
    # The extension is taken from the sanitised name after the allow-list has
    # validated the original, so ``file_type`` records the extension that was
    # actually accepted rather than the one the client claimed.
    _, extension = os.path.splitext(sanitised)
    file_type = extension.lstrip(".").lower()
    relative = f"{uuid_lib.UUID(str(tenant_id))}/{uuid_lib.uuid4()}/{sanitised}"
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


def _upload_directory_id(relative_path: str) -> str:
    """The per-upload uuid directory of a stored path, or ``"-"``.

    Derived from the path rather than passed alongside it because the name
    storage reports back may not be the one that was requested, and this is the
    directory the *stored* file actually landed in - which is the one an
    operator has to look for.

    ``"-"`` rather than the whole path when the shape is not the expected one:
    the fallback exists so that an unexpected path cannot be leaked through the
    log line that was added to keep it out of the logs.
    """
    parts = relative_path.split("/")
    return parts[1] if len(parts) > 2 else "-"


def _discard_upload(relative_path: str, tenant_id) -> None:
    """Delete a stored file whose row failed to land.

    The write is ordered file-then-row, so a failure between the two leaves a
    document nobody owns: readable by no view, counted by no quota, and
    invisible to any cleanup that works from the table. Deleting it here keeps
    storage and rows agreeing.

    The failure is logged by tenant and upload directory and never by path. A
    document is routinely named after the patient it concerns, so the last
    component of a storage path is PHI-adjacent, and this line is the one place
    it would land: it runs unattended, on the failure path, in whatever log
    aggregation ships next, which has a wider readership than the document
    itself. The tenant and the uuid are what an operator needs to find the file
    on disk, so the line stays actionable without naming anything.

    ``exc_info`` is deliberately *not* attached, which is why this is
    ``logger.error`` and not ``logger.exception``: the ``OSError`` that
    ``os.remove`` raises carries the absolute path in its own message, so the
    traceback would restore the filename the format string just removed. The
    exception's class and ``errno`` are logged instead, which is what
    distinguishes a permission failure from a missing file.
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

    Defence in depth, and labelled as such: the upload path cannot produce a
    traversal because the filename is sanitised and the uuid directory is
    server-generated, so this check exists for the case where a row was written
    by some other route - a data migration, an operator's SQL, a future bug -
    and would otherwise be served. Returning 404 rather than 400 keeps the
    refusal indistinguishable from the row not existing.

    The row is the argument rather than its ``file_url`` because the check has
    two halves and only the row carries both of them. Containment under
    ``MEDIA_ROOT`` proves the path is somewhere the server chose to store
    files; it says nothing about *whose* directory that is. A row owned by one
    tenant whose stored path points into another tenant's tree - written the
    same way, by a route the API does not expose - passes containment and
    streams the wrong hospital's document, which is the one failure this
    function is named for. The tenant id is therefore compared against the
    stored path's own first component, and the row is what makes that
    comparison possible.

    A bare ``file_url`` string is deliberately not accepted as the argument:
    the tenant has to come from the row, because a tenant parsed out of the
    path by the caller and compared against the same path is a check that
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

    ``GET /api/v1/feature-flags/`` lists the tenant's flags to any authenticated
    member of it. ``PUT`` (or ``PATCH``) on
    ``/api/v1/feature-flags/{key}/`` sets one, and that is the whole write
    surface: the key is the URL segment (``lookup_field``), the tenant is the
    request's, and the row is created when it does not exist yet.

    **PUT upserts, and that is why POST is not routed.** A feature flag has to be
    settable before it exists - there is no row to PUT on the first time a
    hospital decides to turn something on - and this is the only route that
    creates one. It answers 200 whether or not the row was there, so repeating
    the request is idempotent in status as well as in effect, which is what PUT
    promises and what a 201-then-200 sequence would not.

    DELETE is not routed either: removing the row would leave the feature reading
    as off by absence while erasing the record that anyone decided it, with no
    event in the audit trail to say so. Switching a feature off is a PUT of
    ``enabled: false``.

    ``PATCH`` is the same call with a partial body - it upserts on exactly the
    same terms and changes only the fields it names - because a flag's whole
    state is two short fields and a caller fixing one of them should not have to
    resend the other.

    Writes require a privileged membership in the request's tenant
    (``IsPrivilegedTenantMember``); reads do not, because the client needs the
    configuration to render the right screens whether or not it may change it.
    """

    serializer_class = FeatureFlagSerializer
    #: The URL segment is the flag's key, not its primary key. Tenant scoping is
    #: unchanged and still comes from the mixin's queryset - which is what makes a
    #: cross-tenant key answer 404 rather than naming a row that exists.
    lookup_field = "key"
    #: Ordered so the list is deterministic; see PlatformFileViewSet for why an
    #: unordered queryset is more than untidy under pagination.
    queryset = FeatureFlag.objects.order_by("key")
    http_method_names = ["get", "put", "patch", "head", "options"]

    def update(self, request, *args, **kwargs):
        """Set the named flag, creating it for this tenant if it is new.

        DRF's ``UpdateModelMixin.update`` resolves the object with
        ``get_object()`` and 404s when there is none, which is right for every
        other viewset here and wrong for this one: the flag a hospital is turning
        on does not exist yet. So the row is looked up tenant-scoped first and
        the create branch runs the *same* validation and the *same*
        ``perform_create`` the mixin would have run - which is what keeps the
        tenant stamp and the audit event (AUD-001) on the create path identical
        to every other tenant-owned write in this project.

        A lookup that dropped the tenant filter would overwrite another
        hospital's row here and still answer 200, which is why it goes through
        ``self.get_queryset()`` - the mixin's tenant-scoped queryset - rather than
        the model manager.
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
        from, which on this create path leaves it with nowhere to come from at
        all - so it is injected here rather than by making the field writable and
        asking every caller to keep a body value in step with the path. It is the
        same value ``update`` looked the row up by, and it is validated the same
        way, so a row's key is always a key this viewset would have accepted in
        a URL.
        """
        serializer.validated_data[self.lookup_field] = self._validated_key(
            self.request
        )
        super().perform_create(serializer)

    def _validated_key(self, request) -> str:
        """The flag key from the URL, or a 400 naming why it is unusable.

        This is the one write on the endpoint that no client-side validation
        reaches: the router hands the viewset whatever the path segment spelled,
        and this endpoint stores it. The key becomes part of a feature-gate name
        in code as well as part of a URL, so it is held to a shape both can
        carry - lowercase, digits, ``_`` and ``-`` between them, within the
        column's 64 characters. See :data:`FLAG_KEY_PATTERN` for why ``.`` is
        not among them.

        Refused with a validation error rather than 404 because the key is
        present and the *request* is what is wrong with it. The router's own
        pattern is the wider ``[^/.]+``, so it admits segments this endpoint
        will not store - an uppercase key, an over-long one, a quote - and
        those are answered here with the rule they broke. What the URL cannot
        express at all (``/``, an empty segment, a dotted key) is a 404 that
        never arrives, and no row is written either way.
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
            _discard_upload(stored_path, tenant_id)
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
        is what puts authentication, the tenant filter and both path checks -
        the row's own tenant partition, then containment under ``MEDIA_ROOT`` -
        in front of the bytes.
        """
        platform_file = self.get_object()
        path = _resolve_download_path(platform_file)

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
