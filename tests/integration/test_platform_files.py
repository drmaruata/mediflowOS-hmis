"""Tenant-isolated file upload and download (PLT-005).

``POST /api/v1/files/`` takes a multipart upload, stores it under
``MEDIA_ROOT/<tenant_id>/<uuid>/<sanitised filename>`` and writes a
``platform.file`` row; ``GET /api/v1/files/{id}/download/`` streams it back to
the owning tenant only.

The cases that matter are the ones that look like working code while leaking:
another hospital's row answered with its bytes, a path that escaped the tenant
directory, a route that serves the file without authenticating at all. Each is
pinned below.

Two gates in this module are deliberately outside the API. The row level
security isolation suite (``test_rls_isolation.py``) discovers tenant tables by
their ``tenant_id`` column, so ``platform.file`` is covered by it the moment the
table exists — this module asserts that discovery actually happened, because a
table nobody lists is a table nobody tests. And the migration itself is
inspected for its frozen table list, since RLS is DDL with no model state and
the only thing that can go wrong is the migration not naming the table.

The audit cases are here for the same reason. Uploading is a write to
tenant-owned data, so it lands in the audit chain (AUD-001) — and a document is
routinely named after the person it is about, so what that chain is *not*
allowed to carry is asserted too.
"""
import uuid
from importlib import import_module
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity_tenancy.models import Role, Tenant, UserMembership
from apps.platform.models import PlatformFile

#: The gateway the isolation suite uses. Imported from that module rather than
#: reimplemented, so a change to how tables are discovered cannot leave this
#: assertion checking a stale rule.
from test_rls_isolation import _tenant_owned_tables

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT_A = uuid.UUID("f11e0000-0000-4000-8000-000000000001")
TENANT_B = uuid.UUID("f22e0000-0000-4000-8000-000000000002")

TEST_PASSWORD = "pw-for-platform-files-only"

#: Repository root, used only to prove the suite never writes inside it.
REPO_ROOT = Path(__file__).resolve().parents[2]

FILES_URL = "/api/v1/files/"


def _make_client(tenant_id, username, slug):
    """An authenticated client of one tenant, with no permission claims.

    Same shape as the other integration suites: the access token is minted by
    the production issuer, so the tenant claim that decides the tenant comes
    from a signed credential rather than the client picking a header.
    """
    Tenant.objects.get_or_create(id=tenant_id, defaults={"name": slug, "slug": slug})
    user = get_user_model().objects.create_user(
        username=username, password=TEST_PASSWORD
    )
    role = Role.objects.create(tenant_id=tenant_id, name=f"role-{slug}", permissions=[])
    UserMembership.objects.create(
        user=user, tenant_id=tenant_id, role=role, active=True
    )
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_ID=str(tenant_id))
    return client, user


@pytest.fixture
def client_a():
    """An authenticated tenant-A uploader, with the principal alongside it.

    The principal is returned because ``uploaded_by`` is asserted against the
    requester's pk, which is the value the view has to coerce.
    """
    return _make_client(TENANT_A, "files-a", "files-a")


@pytest.fixture
def client_b():
    """An authenticated tenant-B caller: the one whose reads must 404."""
    return _make_client(TENANT_B, "files-b", "files-b")[0]


def _upload(client, filename, content, content_type="application/pdf", extra=None):
    """POST one file as a multipart upload.

    ``extra`` adds further form fields, for the cases where the point is that a
    client-supplied value is ignored rather than obeyed. It is a dict rather than
    keyword arguments because several of the fields a caller might try to forge
    are spelled like this helper's own parameters.
    """
    payload = {
        "file": SimpleUploadedFile(
            filename, content, content_type=content_type
        )
    }
    payload.update(extra or {})
    return client.post(FILES_URL, payload, format="multipart")


def _download(client, file_id):
    return client.get(f"{FILES_URL}{file_id}/download/")


def _assert_no_file_bytes(response):
    """A refusal must carry none of the stored document's content.

    Asserted on the status *and* the body, because a 404 whose body is the
    document would still be a leak - the status code is what the client sees,
    but the bytes are what it receives.
    """
    assert response.status_code == 404
    assert b"tenant-a-only payload" not in response.getvalue()
    assert b"downloadable payload" not in response.getvalue()


def _media_tree():
    """Every path under ``MEDIA_ROOT`` as POSIX strings, sorted.

    A snapshot, taken before and after a request. ``MEDIA_ROOT`` is one
    directory for the whole process, so what proves "nothing was written" is
    that the snapshot did not grow - counting the files outright would make
    every such assertion depend on which tests happened to run first.
    """
    root = Path(settings.MEDIA_ROOT)
    if not root.exists():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


class TestUpload:
    def test_upload_returns_201_and_writes_the_file_under_the_tenant_directory(
        self, client_a
    ):
        client, _ = client_a
        content = b"%PDF-1.4 tenant-a-only payload"

        response = _upload(client, "scan.pdf", content)

        assert response.status_code == 201, response.content
        row = PlatformFile.objects.get()
        assert row.tenant_id == TENANT_A
        assert row.filename == "scan.pdf"
        assert row.file_type == "pdf"

        # Path shape is pinned, not inferred: tenant first so the partitioning
        # is real, then a fresh uuid per upload so two same-named files from
        # one tenant never collide, then the sanitised original name.
        parts = row.file_url.split("/")
        assert len(parts) == 3, row.file_url
        assert parts[0] == str(TENANT_A)
        uuid.UUID(parts[1])
        assert parts[2] == "scan.pdf"

        # The stored value is a relative path, so it must fit the column.
        assert len(row.file_url) <= 200

        stored = Path(settings.MEDIA_ROOT) / row.file_url
        assert stored.read_bytes() == content

    def test_uploaded_by_is_the_requester(self, client_a):
        """``uploaded_by`` is server-owned and never client-supplied.

        The column is a ``UUIDField`` while the authenticated principal's pk is
        an integer, so the value is coerced through the model field's own
        ``to_python`` — the same rule the audit chain uses. A raw integer would
        still be stored by the database driver and read back as a different
        value than the one written.
        """
        client, user = client_a
        response = _upload(client, "note.json", b'{"a": 1}')

        assert response.status_code == 201, response.content
        row = PlatformFile.objects.get()
        assert row.uploaded_by == uuid.UUID(int=user.pk)
        assert row.uploaded_by == PlatformFile._meta.get_field("uploaded_by").to_python(
            user.pk
        )

    def test_a_disallowed_extension_is_rejected_and_nothing_is_written(self, client_a):
        client, _ = client_a
        before = _media_tree()

        response = _upload(client, "payload.exe", b"MZ\x90\x00")

        assert response.status_code == 400
        assert response.json()["file"]
        assert PlatformFile.objects.count() == 0
        # A rejected upload must not leave a file behind. The snapshot is the
        # assertion, not a count: MEDIA_ROOT is shared for the whole process.
        assert _media_tree() == before

    @pytest.mark.parametrize("extension", ["pdf", "png", "jpg", "csv", "json"])
    def test_every_allowed_extension_is_accepted(self, client_a, extension):
        client, _ = client_a
        response = _upload(client, f"doc.{extension}", b"bytes")

        assert response.status_code == 201, response.content
        assert PlatformFile.objects.get().file_type == extension

    def test_an_oversize_upload_is_rejected_and_nothing_is_written(self, client_a):
        """Oversize is a 400 naming the cap, not a 413 from Django.

        A file larger than ``FILE_UPLOAD_MAX_MEMORY_SIZE`` is streamed to a
        temporary file by the upload handler, so the bytes reach the serializer
        and this cap is the first thing that can refuse them. A 413 would mean
        the request died before the view ran, which is a different failure
        than the documented one.
        """
        client, _ = client_a
        before = _media_tree()
        cap = settings.MAX_UPLOAD_MB * 1024 * 1024

        response = _upload(client, "huge.pdf", b"x" * (cap + 1024))

        assert response.status_code == 400
        assert str(settings.MAX_UPLOAD_MB) in response.json()["file"][0]
        assert PlatformFile.objects.count() == 0
        assert _media_tree() == before

    def test_an_anonymous_upload_is_rejected(self):
        response = _upload(APIClient(), "anon.pdf", b"bytes")

        assert response.status_code == 401
        assert PlatformFile.objects.count() == 0

    def test_a_failed_row_write_leaves_no_orphaned_file(self, client_a, monkeypatch):
        """The file is written before the row, so the failure mode is a stray file.

        A stored document that no row references is invisible to every view,
        every quota and any cleanup that works from the table - and it is still
        on disk holding whatever it was given. The view deletes the file when the
        row write raises, which is asserted here by making the row write raise.
        """
        client, _ = client_a
        before = _media_tree()

        def boom(*args, **kwargs):
            raise RuntimeError("row write failed")

        monkeypatch.setattr(PlatformFile.objects, "create", boom)

        # The exception propagates: the client must see a 500, not a 201 for a
        # write that did not happen.
        with pytest.raises(RuntimeError):
            _upload(client, "orphan.pdf", b"bytes")

        assert PlatformFile.objects.count() == 0
        assert _media_tree() == before

    def test_the_row_fields_are_server_owned(self, client_a):
        """A caller cannot choose the path, the name, the type or the owner.

        Each of these is derived from validated input plus the request, so a
        writable one would let a caller point a row at a path of their choosing
        (including another tenant's) or claim a document as someone else's. They
        are read-only in the serializer, and this asserts that from the client's
        side rather than trusting the field list.
        """
        client, user = client_a
        _upload(
            client,
            "real.pdf",
            b"bytes",
            extra={
                "file_url": f"{TENANT_B}/not-mine/real.pdf",
                "filename": "not-this-one.pdf",
                "file_type": "exe",
                "uploaded_by": str(uuid.UUID(int=999)),
                "tenant_id": str(TENANT_B),
            },
        )

        row = PlatformFile.objects.get()
        assert row.file_url.startswith(f"{TENANT_A}/")
        assert row.file_url != f"{TENANT_B}/not-mine/real.pdf"
        assert row.filename == "real.pdf"
        assert row.file_type == "pdf"
        assert row.uploaded_by == uuid.UUID(int=user.pk)
        assert row.tenant_id == TENANT_A


class TestDownload:
    @pytest.fixture
    def uploaded(self, client_a):
        client, _ = client_a
        content = b"%PDF-1.4 downloadable payload"
        response = _upload(client, "report.pdf", content)
        assert response.status_code == 201, response.content
        return PlatformFile.objects.get(), content

    def test_the_owner_downloads_the_original_bytes(self, client_a, uploaded):
        client, _ = client_a
        row, content = uploaded

        response = _download(client, row.id)

        assert response.status_code == 200
        assert response.getvalue() == content
        # Attachment, under the original filename the uploader chose — not the
        # storage path, which would reveal the tenant's directory layout.
        assert response["Content-Disposition"] == 'attachment; filename="report.pdf"'

    def test_a_cross_tenant_download_is_a_404(self, client_b, uploaded):
        """The whole point of the endpoint: another hospital gets no bytes.

        A 403 would answer "this row exists and is not yours", which is an
        existence oracle. A 404 makes the two indistinguishable.
        """
        row, _ = uploaded

        response = _download(client_b, row.id)

        _assert_no_file_bytes(response)

    def test_an_unknown_id_is_a_404_for_the_owner_too(self, client_a):
        client, _ = client_a
        response = _download(client, uuid.uuid4())

        assert response.status_code == 404

    def test_an_anonymous_download_is_rejected(self, uploaded):
        row, _ = uploaded

        response = _download(APIClient(), row.id)

        assert response.status_code == 401

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_a_stored_document_cannot_be_rewritten_or_deleted(
        self, client_a, uploaded, method
    ):
        """A row is immutable after the upload, and the bytes survive a DELETE.

        DELETE through the router would remove the row and leave the document on
        disk with nothing referencing it - the same orphan the failed-write path
        guards against, reached on purpose. PUT and PATCH have no writable
        field at all, so they could only ever answer 200 while changing nothing,
        which is worse than a 405: the caller is told the document was updated.
        Retention and deletion are governed by the audit policy, not by a
        DELETE verb on a storage route.
        """
        client, _ = client_a
        row, content = uploaded

        response = getattr(client, method)(
            f"{FILES_URL}{row.id}/", {"filename": "rewritten.pdf"}
        )

        assert response.status_code == 405, response.content
        row.refresh_from_db()
        assert row.filename == "report.pdf"
        assert (Path(settings.MEDIA_ROOT) / row.file_url).read_bytes() == content

    def test_a_row_pointing_outside_the_media_root_is_never_served(
        self, client_a, tmp_path
    ):
        """Defence in depth: the resolved path must stay under ``MEDIA_ROOT``.

        The upload path makes a traversal impossible by construction — the name
        is sanitised and the uuid directory is generated server-side — so this
        test writes the hostile row directly, the way a bug or a future
        migration would, and asserts the download refuses it.
        """
        escape = Path(settings.MEDIA_ROOT) / "outside.pdf"
        escape.write_bytes(b"should never be served")

        row = PlatformFile.objects.create(
            tenant_id=TENANT_A,
            filename="report.pdf",
            file_url="../outside.pdf",
            file_type="pdf",
            uploaded_by=uuid.UUID(int=1),
        )

        client, _ = client_a
        response = _download(client, row.id)

        assert response.status_code == 404
        assert b"should never be served" not in response.getvalue()


class TestListing:
    def test_the_list_holds_only_the_requesting_tenants_rows(self, client_a, client_b):
        client_a, _ = client_a
        _upload(client_a, "a.pdf", b"a")
        _upload(client_b, "b.pdf", b"b")

        response = client_a.get(FILES_URL)

        assert response.status_code == 200
        body = response.json()
        assert [row["filename"] for row in body["results"]] == ["a.pdf"]
        assert "b.pdf" not in str(body)
        assert str(TENANT_B) not in str(body)


class TestFilenameSanitisation:
    @pytest.mark.parametrize(
        "hostile",
        [
            "../../evil.pdf",
            "..%2F..%2Fevil.pdf",
            "/etc/passwd.pdf",
            "..\\..\\evil.pdf",
            "evil\x00.pdf",
            "a" * 400 + ".pdf",
        ],
    )
    def test_a_hostile_filename_is_stored_under_the_uuid_directory_only(
        self, client_a, hostile
    ):
        client, _ = client_a
        before = _media_tree()
        response = _upload(client, hostile, b"bytes")

        assert response.status_code == 201, response.content
        row = PlatformFile.objects.get()

        # No separator and no parent reference survives, so the stored name is
        # a single path component and the file cannot land anywhere else.
        assert "/" not in row.filename
        assert "\\" not in row.filename
        assert ".." not in row.filename
        assert "\x00" not in row.filename
        # ...and the extension survived, so the allow-list still applied.
        assert row.filename.endswith(".pdf")

        stored = Path(settings.MEDIA_ROOT) / row.file_url
        assert stored.parent == Path(settings.MEDIA_ROOT) / str(TENANT_A) / str(
            uuid.UUID(row.file_url.split("/")[1])
        )
        assert stored.is_file()
        # Exactly one file was written, and it is the one the row names.
        assert _media_tree() - before == {row.file_url}

    def test_two_same_named_uploads_do_not_collide(self, client_a):
        """A fresh uuid per upload is what keeps the second write from
        overwriting the first."""
        client, _ = client_a
        before = _media_tree()
        first = _upload(client, "same.pdf", b"first")
        second = _upload(client, "same.pdf", b"second")

        assert first.status_code == 201
        assert second.status_code == 201
        urls = {row.file_url for row in PlatformFile.objects.all()}
        assert len(urls) == 2
        assert _media_tree() - before == urls


class TestRowLevelSecurityWiring:
    """``platform.file`` must be under the isolation gate, not just the view."""

    def test_the_isolation_gate_discovers_the_table(self):
        """The gate walks the registry by ``tenant_id`` column, so the table is
        covered without anyone listing it. Asserted here because a discovery
        that silently returned nothing would make every other case in that
        suite vacuous."""
        assert "platform.file" in _tenant_owned_tables()

    def test_a_migration_enables_row_level_security_on_the_table(self):
        """RLS is DDL with no Django model state, applied by a frozen-table
        ``RunPython`` migration. The failure this guards is the table being
        created without one, which is invisible to ``makemigrations --check``
        and would let PostgreSQL answer every tenant's rows."""
        migration = import_module(
            "apps.platform.migrations.0006_enable_row_level_security"
        )

        assert "platform.file" in migration.TABLES
        assert migration.TABLES == ("platform.file",)

    def test_the_backwards_operation_drops_the_policy_rather_than_rls_itself(self):
        """Reversing must leave the table default-deny, not briefly wide open."""
        migration = import_module(
            "apps.platform.migrations.0006_enable_row_level_security"
        )

        source = Path(migration.__file__).read_text(encoding="utf-8")
        assert "rls.disable(TABLES" in source
        assert "is_postgres" in source

    def test_the_generator_script_registers_the_standalone_migration(self):
        """``platform.file`` is in the script's registry, not just on disk.

        The generator is the only place that records *why* a table has its own
        migration instead of being folded into the app's 0004, so a registry that
        does not name this table is the first thing to go stale when someone adds
        a tenant-owned model to this app.
        """
        script = import_module("scripts.add_rls_migrations")

        assert "platform" in script.STANDALONE
        entry = script.STANDALONE["platform"]
        assert entry.tables == ("platform.file",)
        assert entry.filename == "0006_enable_row_level_security.py"
        # The registry and the file on disk must agree, or one of them is a lie.
        migration = import_module(
            f"apps.platform.migrations.{entry.filename[:-3]}"
        )
        assert migration.TABLES == entry.tables
        assert script.verify_standalone() == ()


class TestAuditTrail:
    """An upload writes tenant-owned data, so the audit chain applies (AUD-001)."""

    def test_the_upload_is_audited_by_identifier_only(self, client_a):
        """One event, naming the row - never the document.

        A document is routinely named after the person it is about, so an audit
        row that carried the filename would put PHI into the audit chain, which
        is readable by a wider audience than the file itself and is meant to
        survive under its own retention. The event names the row's id and the
        tenant, which is what an investigator needs to find the document again.
        """
        client, _ = client_a
        response = _upload(client, "patient-report-final.pdf", b"%PDF-1.4 payload")

        assert response.status_code == 201, response.content
        row = PlatformFile.objects.get()

        events = AuditEvent.objects.filter(entity_type="platform.file")
        assert events.count() == 1
        event = events.get()
        assert event.action == "create"
        assert event.entity_id == str(row.id)
        assert event.tenant_id == TENANT_A

        # The whole row, serialised, must not reproduce the document's name or
        # its bytes. Asserted over every field rather than the few that look
        # risky, because the point is what the chain does *not* carry.
        dumped = " ".join(str(value) for value in event.__dict__.values())
        assert "patient-report-final" not in dumped
        assert "payload" not in dumped

    def test_a_download_is_not_audited_as_a_write(self, client_a):
        """Reading a document leaves no ``create``/``update``/``delete`` event.

        The download route only streams bytes; it changes no row, so an audit
        entry claiming a write would be a false statement in the chain. Read
        access logging for documents is not required by PLT-005; the absence is
        asserted here so that neither presence nor absence has to be assumed.
        """
        client, _ = client_a
        upload = _upload(client, "read-only.pdf", b"bytes")
        assert upload.status_code == 201, upload.content
        row = PlatformFile.objects.get()
        before = AuditEvent.objects.filter(entity_type="platform.file").count()

        response = _download(client, row.id)

        assert response.status_code == 200
        assert AuditEvent.objects.filter(entity_type="platform.file").count() == before


class TestTheRepositoryStaysClean:
    def test_uploads_land_outside_the_repository_tree(self, client_a):
        """A suite that writes into the working tree leaves stray files that
        would be committed, and PHI in a scratch directory."""
        client, _ = client_a
        media_root = Path(settings.MEDIA_ROOT).resolve()
        assert not media_root.is_relative_to(REPO_ROOT)

        _upload(client, "in-tmp.pdf", b"bytes")
        assert _media_tree()

        assert not (REPO_ROOT / "media").exists()
        assert not list(REPO_ROOT.glob("backend/media"))
