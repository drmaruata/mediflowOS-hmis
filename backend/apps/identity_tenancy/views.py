"""Identity and administration views."""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Case, IntegerField, When
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from common.tenant import TENANT_REQUIRED_MESSAGE, TenantScopedQuerysetMixin
from . import csv_io
from .models import (
    SETUP_STEPS,
    BaselineInput,
    BreakGlassAccess,
    ConfigRevision,
    Department,
    Facility,
    ReferenceData,
    Role,
    ServiceUnit,
    SetupProgress,
    StaffPosition,
    Tenant,
    Ward,
    Bed,
    UserMembership,
)
from .permissions import RequirePermission, WritePermissionMixin
from .serializers import (
    BaselineInputSerializer,
    BreakGlassAccessSerializer,
    ConfigRevisionSerializer,
    DepartmentSerializer,
    FacilitySerializer,
    ReferenceDataSerializer,
    RoleSerializer,
    ServiceUnitSerializer,
    SetupProgressSerializer,
    StaffPositionSerializer,
    TenantSerializer,
    WardSerializer,
    BedSerializer,
    UserMembershipSerializer,
    UserCreateSerializer,
    UserSerializer,
    OnboardTenantSerializer,
)
from .services import record_revision


class TenantViewSet(viewsets.ModelViewSet):
    """Tenants are the tenancy root, so they are not tenant-scoped.

    They are platform-owned instead: every method — list, detail, create and
    the onboard action — requires the ``platform.tenants.manage`` claim
    (TEN-004, TEN-010), which the platform-scope role (``Role.tenant is None``)
    is expected to hold. A tenant administrator must be able to neither
    enumerate other hospitals' tenants nor mint new ones.
    """
    serializer_class = TenantSerializer
    queryset = Tenant.objects.all()

    def get_permissions(self):
        # Appended after the defaults, so anonymous requests still fail as 401
        # (IsAuthenticated first) and the MFA gate stays in force — see
        # common/mfa.py on views replacing DEFAULT_PERMISSION_CLASSES.
        return [*super().get_permissions(), RequirePermission("platform.tenants.manage")]

    @extend_schema(
        request=OnboardTenantSerializer,
        responses={201: TenantSerializer},
    )
    @action(detail=False, methods=["post"])
    def onboard(self, request):
        """Repeatable tenant onboarding with seed configuration (TEN-010).

        One service call mints the tenant, its first facility, the default
        departments and roles, and the first admin account inside a single
        transaction. ``Tenant.slug`` is globally unique, so a second boarding
        of the same hospital is a state conflict the caller must reconcile —
        answered 409, not the 400 a UniqueValidator would give or the 500 an
        uncaught IntegrityError would.
        """
        serializer = OnboardTenantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tenant = serializer.save()
        except IntegrityError:
            return Response(
                {
                    "detail": (
                        f"A tenant with slug '{request.data.get('slug')}' "
                        "already exists."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(TenantSerializer(tenant).data, status=status.HTTP_201_CREATED)


class FacilityViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = FacilitySerializer
    queryset = Facility.objects.all()


class EffectiveDatedConfigMixin:
    """Effective dating and the no-hard-delete rule for configuration (SET-010, SET-011).

    Configuration rows are referenced by audit history and — once indicator
    periods exist — by locked reporting periods, so they are never hard
    deleted: DELETE is not a routed verb (the framework answers 405 without
    resolving any object), and deactivation is ``PATCH {active: false}``,
    which keeps the row (SET-011). Every update first archives the row's
    *pre-update* state into ``ConfigRevision`` and then applies the new
    values (SET-010).

    ``record_revision`` runs on ``serializer.instance``, which still holds the
    committed values the serializer was bound to — the save happens in
    ``super().perform_update`` below it — so the snapshot can never contain the
    new configuration. Close and save share one explicit transaction, because
    ``ATOMIC_REQUESTS`` is False in the test profile and a revision without its
    update (or an update without its revision) would both be wrong.
    """

    #: DELETE never routes on config resources; see the class docstring.
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def perform_update(self, serializer):
        with transaction.atomic():
            record_revision(serializer.instance, self.request.user)
            super().perform_update(serializer)


class DepartmentViewSet(
    EffectiveDatedConfigMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet
):
    """Department configuration (SET-002).

    Creates and PATCHes land the tenant mixin's audit event (SET-012) and
    effective-date the pre-update state (SET-010); DELETE is refused 405
    (SET-011) — deactivation is ``PATCH {active: false}``.

    ``GET ?opd_enabled=true`` narrows the list to departments the OPD token
    picker can select (REG-012).
    """
    serializer_class = DepartmentSerializer
    queryset = Department.objects.all()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="opd_enabled",
                description=(
                    "When 'true', list only departments the OPD picker can "
                    "select (REG-012, the model's existing opd_enabled "
                    "flag). Any other or absent value leaves the list "
                    "unfiltered."
                ),
                required=False,
            ),
        ],
        responses={200: DepartmentSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        # Only the literal "true" opts the filter in (mirrors SET-008's
        # ``incomplete=`` parse): an ambiguous value must not silently empty
        # the picker, which would look like a working filter.
        if self.request.query_params.get("opd_enabled", "").lower() == "true":
            queryset = queryset.filter(opd_enabled=True)
        return queryset


class WardViewSet(
    EffectiveDatedConfigMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet
):
    """Ward configuration under a department (SET-003)."""
    serializer_class = WardSerializer
    queryset = Ward.objects.all()


class BedViewSet(
    EffectiveDatedConfigMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet
):
    """Bed configuration under a ward (SET-003), including the ``active`` flag (SET-011)."""
    serializer_class = BedSerializer
    queryset = Bed.objects.all()

    @extend_schema(
        responses={200: OpenApiTypes.BINARY},
        description=(
            "Download this tenant's beds as a CSV attachment (SET-013). "
            "Columns: ward, bed_number, functional, active — ward is the "
            "ward's name."
        ),
    )
    @action(detail=False, methods=["get"])
    def export(self, request):
        """Download the tenant's beds as a CSV attachment (SET-013).

        ``self.get_queryset()`` applies the tenant-scoped mixin, so the
        document holds this hospital's beds only; the header row is the fixed
        SET-013 column set, ``ward`` as the ward's *name* so the matching
        import can resolve it back within the tenant.
        """
        queryset = self.get_queryset().select_related("ward").order_by(
            "ward__name", "bed_number"
        )
        response = HttpResponse(
            csv_io.render_beds_csv(queryset), content_type="text/csv"
        )
        response["Content-Disposition"] = 'attachment; filename="beds.csv"'
        return response

    @extend_schema(
        request=csv_io.CsvImportFileSerializer,
        responses={200: csv_io.CsvImportResultSerializer},
        description=(
            "Import beds from a CSV upload (SET-013). Every row is validated "
            "against the bed serializer and this tenant's wards before any "
            "row is written; a single bad row writes nothing. Updated rows "
            "archive a ConfigRevision (SET-010) and every written row lands "
            "an AuditEvent (SET-012), mirroring the config viewsets."
        ),
    )
    @action(detail=False, methods=["post"], url_path="import")
    def import_rows(self, request):
        """Import beds from a CSV upload, all-or-nothing (SET-013).

        The upload is read through the wrapper serializer (a missing file is
        a 400), then ``parse_rows`` refuses a malformed document as a 422
        before row inspection, and ``import_beds`` validates every row before
        writing any — the atomicity is explicit in code because
        ``ATOMIC_REQUESTS`` is False in the test profile. The tenant guard
        mirrors ``TenantScopedQuerysetMixin.perform_create``: without a
        resolved tenant there is nothing to scope the writes to. Imports do
        not route through the mixin hooks (that is why no double-audit is
        possible), so ``import_beds`` mirrors them itself: updated rows first
        archive their pre-update state via ``record_revision`` (SET-010) and
        every written row lands one ``AuditEvent`` (SET-012), attributed to
        the acting ``request.user``.
        """
        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied(TENANT_REQUIRED_MESSAGE)
        upload = csv_io.CsvImportFileSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        rows = csv_io.parse_rows(upload.validated_data["file"], csv_io.BED_COLUMNS)
        return Response(csv_io.import_beds(tenant_id, rows, self.request.user))


class ServiceUnitViewSet(
    EffectiveDatedConfigMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet
):
    """Service units without beds (SET-004)."""
    serializer_class = ServiceUnitSerializer
    queryset = ServiceUnit.objects.all()


class StaffPositionViewSet(
    EffectiveDatedConfigMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet
):
    """Staff positions by designation, specialty and department (SET-005).

    The CSV surface (SET-013) mirrors the beds one: export downloads the
    tenant's positions with the department as its name, import validates every
    row before writing any, and the (department, designation) natural key
    turns a re-imported export into in-place updates rather than duplicates.
    """
    serializer_class = StaffPositionSerializer
    queryset = StaffPosition.objects.all()

    @extend_schema(
        responses={200: OpenApiTypes.BINARY},
        description=(
            "Download this tenant's staff positions as a CSV attachment "
            "(SET-013). Columns: department, designation, specialty, "
            "sanctioned, in_position — department is the department's name."
        ),
    )
    @action(detail=False, methods=["get"])
    def export(self, request):
        """Download the tenant's staff positions as a CSV attachment (SET-013).

        ``self.get_queryset()`` applies the tenant-scoped mixin, so the
        document holds this hospital's positions only; the column set is
        derived from the model (the department as its name plus the four
        public scalar fields) and deliberately omits ``active``, which
        ``StaffPosition`` does not have.
        """
        queryset = self.get_queryset().select_related("department").order_by(
            "department__name", "designation"
        )
        response = HttpResponse(
            csv_io.render_staff_positions_csv(queryset), content_type="text/csv"
        )
        response["Content-Disposition"] = 'attachment; filename="staff-positions.csv"'
        return response

    @extend_schema(
        request=csv_io.CsvImportFileSerializer,
        responses={200: csv_io.CsvImportResultSerializer},
        description=(
            "Import staff positions from a CSV upload (SET-013). Every row is "
            "validated against the position serializer and this tenant's "
            "departments before any row is written; a single bad row writes "
            "nothing. Updated rows archive a ConfigRevision (SET-010) and "
            "every written row lands an AuditEvent (SET-012)."
        ),
    )
    @action(detail=False, methods=["post"], url_path="import")
    def import_rows(self, request):
        """Import staff positions from a CSV upload, all-or-nothing (SET-013).

        Same shape as the beds import: wrapper serializer for the upload, 422
        for a malformed document, row-by-row validation through
        ``StaffPositionSerializer`` with department resolution scoped to the
        caller's tenant, then one explicit transaction only when every row is
        valid. The history contract is mirrored from the beds surface too:
        updated rows archive their pre-update state via ``record_revision``
        (SET-010) and every written row lands one ``AuditEvent`` (SET-012),
        attributed to the acting ``request.user``.
        """
        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied(TENANT_REQUIRED_MESSAGE)
        upload = csv_io.CsvImportFileSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        rows = csv_io.parse_rows(
            upload.validated_data["file"], csv_io.STAFF_POSITION_COLUMNS
        )
        return Response(csv_io.import_staff_positions(tenant_id, rows, self.request.user))


class ConfigRevisionViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """Effective-dated configuration history (SET-010).

    Read-only: revisions are written only by ``record_revision`` on update.
    ``?entity=`` and ``?entity_id=`` narrow the history to one table and one
    row (both optional); without them the endpoint lists the tenant's whole
    revision log. The current (open, ``effective_to`` null) revision sorts
    first, then older periods by ``effective_from`` descending, then id — the
    open-first ordering is what an admin screen reads the current settings
    from, and it is deterministic across the two databases the suite and
    production run on, where NULL ordering rules differ.
    """

    serializer_class = ConfigRevisionSerializer
    queryset = ConfigRevision.objects.all()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="entity",
                description=(
                    "Restrict to one configuration table's history, e.g. "
                    "'identity.department' (the model's db_table)."
                ),
                required=False,
            ),
            OpenApiParameter(
                name="entity_id",
                description=(
                    "Restrict to one row's history within ``entity`` "
                    "(a UUID, matching the archived row's id)."
                ),
                required=False,
            ),
        ],
        responses={200: ConfigRevisionSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        entity = self.request.query_params.get("entity")
        entity_id = self.request.query_params.get("entity_id")
        if entity:
            queryset = queryset.filter(entity=entity)
        if entity_id:
            queryset = queryset.filter(entity_id=entity_id)
        # Open revisions (effective_to null) first — see the class docstring.
        # ``Case/When`` rather than dialect NULLS FIRST so the ordering is
        # identical on SQLite (test suite) and PostgreSQL (production).
        return queryset.annotate(
            _open=Case(
                When(effective_to__isnull=True, then=0),
                default=1,
                output_field=IntegerField(),
            )
        ).order_by("_open", "-effective_from", "-id")


class RoleViewSet(WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Role management (TEN-004).

    Scoping keeps each hospital's role catalogue — names and permission
    bundles — out of every other tenant's list. Platform-scope roles
    (``tenant is None``) belong to no tenant's list either: exposing them
    here would let a tenant administrator edit the platform's own roles.
    Writes require the ``identity.roles.write`` claim.
    """
    serializer_class = RoleSerializer
    queryset = Role.objects.all()
    write_permission = "identity.roles.write"


class UserMembershipViewSet(WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Tenant membership assignment (TEN-004).

    Tenant stamping and the audit trail (AUD-001) both come from
    ``TenantScopedQuerysetMixin``'s ``perform_*`` hooks — the local
    ``perform_create`` this viewset used to carry duplicated the stamping and
    wrote no audit row. Writes require the ``identity.memberships.write`` claim.
    """
    serializer_class = UserMembershipSerializer
    queryset = UserMembership.objects.all()
    write_permission = "identity.memberships.write"


class UserViewSet(WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    """Tenant user management (TEN-008).

    ``auth.User`` has no tenant column, so scoping runs through the
    membership join (``tenant_field = "memberships__tenant_id"``): a
    cross-tenant detail lookup resolves nothing and 404s, never 403s — the
    existence of another hospital's account is itself not disclosed. Writes
    (create, patch, deactivate) require the ``identity.users.manage`` claim;
    reads are authorised by the authenticated principal plus tenant scoping,
    the same contract ``WritePermissionMixin`` states for roles. DELETE and
    PUT are not routed at all: offboarding is deactivation
    (``POST {id}/deactivate/``), because deleting the account would orphan
    every audit row pointing at it, and unbounded replaces (PUT) are not part
    of the interface.
    """
    serializer_class = UserSerializer
    queryset = get_user_model().objects.prefetch_related("memberships")
    write_permission = "identity.users.manage"
    #: No "delete" or "put": see the docstring — deactivation is the only
    #: offboarding path, so ModelViewSet's generated destroy must not route.
    http_method_names = ["get", "post", "patch", "head", "options"]
    #: auth.User has no tenant_id column; the UserMembership join is the
    #: tenant binding. unique_together(user, tenant) guarantees at most one
    #: matching row per tenant, so the join cannot duplicate list results.
    tenant_field = "memberships__tenant_id"

    def get_serializer_class(self):
        """POST create gets the write serializer; every other verb reads."""
        if self.action == "create":
            return UserCreateSerializer
        return UserSerializer

    @extend_schema(request=UserCreateSerializer, responses={201: UserSerializer})
    def create(self, request, *args, **kwargs):
        """Declared only so the schema records both shapes.

        Without it drf-spectacular documents the 201 body as
        UserCreateSerializer's fields, which omit the id and membership
        state the endpoint actually returns; behaviour is unchanged.
        """
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Stamp the tenant, create atomically, write the AUD-001 event.

        The mixin's own ``perform_create`` would call
        ``serializer.save(memberships__tenant_id=...)`` — a keyword that
        cannot write a join row — so the stamp is passed as ``tenant_id``
        for the serializer's ``create()`` to consume, and the mixin's
        tenant guard and audit call are replicated here. The transaction is
        explicit because ``ATOMIC_REQUESTS`` is False in the test profile:
        the user row and its membership must land together or not at all.
        """
        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied(TENANT_REQUIRED_MESSAGE)
        serializer.save(tenant_id=tenant_id)
        self._write_audit_log(serializer.instance, "create")

    @extend_schema(responses=UserSerializer)
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Switch this tenant's membership off instead of deleting the user (TEN-008).

        The account row survives so audit history stays resolvable, and
        ``TenantAwareTokenSerializer.validate`` refuses the next login. An
        already-deactivated membership is the same end state: 200 without a
        second audit row, so retries are harmless.
        """
        user = self.get_object()  # tenant-scoped: a foreign id 404s here
        # Read the membership through ``user.memberships`` rather than a fresh
        # query: the queryset prefetches, so a separately-fetched instance
        # would leave the prefetched row stale and the serialized response
        # would report ``active: true`` right after flipping it to false.
        membership = next(
            (
                m
                for m in user.memberships.all()
                if str(m.tenant_id) == str(self.get_tenant_id())
            ),
            None,
        )
        if membership is None:
            # Unreachable while the queryset joins on the same tenant — only
            # a concurrent delete could land here. 404 rather than a 500.
            raise NotFound("No membership for this user in the current tenant.")
        if membership.active:
            membership.active = False
            membership.save(update_fields=["active"])
            self._write_audit_log(user, "deactivate")
        return Response(self.get_serializer(user).data)


class BreakGlassViewSet(TenantScopedQuerysetMixin, viewsets.GenericViewSet):
    """Recorded break-glass access: administrative listing and revocation (TEN-007).

    The grant stays on ``auth_views.BreakGlassView`` (``POST /auth/break-glass/``),
    which enforces the role claim, the mandatory reason header and the AUD-001
    and alert writes. This viewset is the administrative half: the
    tenant-scoped record list an audit screen (Task 34) reads, and the revoke
    action that ends a grant.

    Every method demands the ``identity.break_glass.revoke`` claim, appended
    after the defaults the same way ``TenantViewSet`` appends one platform
    claim over every method — listing grants is as sensitive as revoking one,
    so a single gate covers both rather than leaving the list behind.
    """

    serializer_class = BreakGlassAccessSerializer
    queryset = BreakGlassAccess.objects.all()

    # No ``permission_classes`` attribute: declaring one would replace the
    # project defaults (IsAuthenticated + MFARequiredIfConfigured) wholesale —
    # see base.py on views that declare their own. Inheriting them keeps the
    # TEN-006 MFA gate in force over list and revoke exactly as TenantViewSet
    # does, and ``get_permissions`` below appends the claim check after them.
    def get_permissions(self):
        return [*super().get_permissions(), RequirePermission("identity.break_glass.revoke")]

    @extend_schema(responses=BreakGlassAccessSerializer(many=True))
    def list(self, request):
        return Response(
            BreakGlassAccessSerializer(self.get_queryset(), many=True).data
        )

    @extend_schema(
        responses=BreakGlassAccessSerializer,
        description=(
            "Revoke a break-glass grant (TEN-007). GET is what the interface "
            "specifies; the action is idempotent — a retried revoke restamps "
            "revoked_at and answers 200 again."
        ),
    )
    @action(detail=True, methods=["get"])
    def revoke(self, request, pk=None):
        """Stamp ``revoked_at`` so the grant no longer passes its check (TEN-007).

        ``self.get_object()`` resolves through the tenant-scoped queryset, so
        a foreign or unknown id answers 404 before any write — the existence
        of another hospital's grant is not disclosed, and this request can
        never touch it. An already-revoked grant is the same end state:
        re-stamping is harmless, so retries are idempotent.
        """
        access = self.get_object()
        access.revoked_at = timezone.now()
        access.save(update_fields=["revoked_at"])
        return Response(BreakGlassAccessSerializer(access).data)


class SetupProgressViewSet(
    WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.GenericViewSet
):
    """Resumable setup wizard state (SET-001, SET-008, SET-009).

    ``GET /setup/`` is *orchestrated*, not a queryset dump: the declared
    ordered step list (``SETUP_STEPS``) is the spine, and stored rows only
    supply each step's saved state — a step with no row still appears as a
    pending, incomplete step, which is what lets a resumed session see the
    whole wizard and what ``?incomplete=true`` narrows to (SET-008).
    ``PUT /setup/{step_key}/`` upserts one step's state: the
    ``(tenant_id, step_key)`` uniqueness makes a resumption update the same
    row rather than stack duplicates.

    Writes are gated on the ``identity.setup.manage`` claim via
    ``WritePermissionMixin``; reads stay authorised by authentication plus
    tenant scoping like every other tenant-owned resource. The tenant guard
    and the AUD-001/SET-012 audit event are replicated from
    ``TenantScopedQuerysetMixin``'s hooks because the upsert goes through
    ``update_or_create`` rather than ``serializer.save()`` — the same reason
    ``UserViewSet.perform_create`` replicates them.
    """

    serializer_class = SetupProgressSerializer
    queryset = SetupProgress.objects.all()
    write_permission = "identity.setup.manage"

    def _step_summary(self, step_key: str, row: SetupProgress | None) -> dict:
        """One wizard step's canonical representation (SET-001, SET-008).

        A step with no stored row renders as the model default — ``pending``,
        no payload, not complete — so the list built from this helper always
        covers the full wizard. Rows reuse the serializer so the ``complete``
        flag is computed in exactly one place; an absent row has nothing to
        serialize, so its defaults are spelled out here.
        """
        if row is None:
            return {
                "step_key": step_key,
                "status": SetupProgress.Status.PENDING,
                "payload": None,
                "complete": False,
                "updated_at": None,
            }
        return self.get_serializer(row).data

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="incomplete",
                description=(
                    "When exactly 'true', return only steps whose status is "
                    "not 'complete' (SET-008)."
                ),
                required=False,
            ),
        ],
        responses={200: SetupProgressSerializer(many=True)},
    )
    def list(self, request):
        """The ordered wizard, each step flagged complete or not (SET-001, SET-008).

        ``incomplete=true`` filters the same orchestrated list to the steps a
        resumed session still has to finish; the flag on each item is what
        the frontend stepper keys off either way. Only the literal ``true``
        opts in, so an arbitrary or malformed value cannot silently truncate
        what the UI shows.
        """
        rows = {row.step_key: row for row in self.get_queryset()}
        only_incomplete = request.query_params.get("incomplete", "").lower() == "true"

        items = []
        for step_key in SETUP_STEPS:
            item = self._step_summary(step_key, rows.get(step_key))
            if only_incomplete and item["complete"]:
                continue
            items.append(item)
        return Response(items)

    @extend_schema(
        request=SetupProgressSerializer,
        responses={200: SetupProgressSerializer},
    )
    def update(self, request, pk=None):
        """Upsert one step's saved state; re-PUT updates the same row (SET-001).

        The step key is validated against the declared wizard before any write
        so a typo 404s instead of minting a row the orchestrated list would
        never render. ``update_or_create`` turns a resumed session's PUT into
        an update of the existing row (the unique ``(tenant_id, step_key)``
        contract), and the answer is 200 whether the row was created or
        refreshed — PUT is idempotent, so the client never needs to branch on
        201 vs 200. The audit event records ``create`` or ``update`` per the
        row's actual fate (SET-012).
        """
        if pk not in SETUP_STEPS:
            raise NotFound(f"Unknown setup step: {pk!r}.")
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied(TENANT_REQUIRED_MESSAGE)

        step, created = SetupProgress.objects.update_or_create(
            tenant_id=tenant_id,
            step_key=pk,
            defaults=serializer.validated_data,
        )
        self._write_audit_log(step, "create" if created else "update")
        return Response(
            self._step_summary(pk, step), status=status.HTTP_200_OK
        )


class ReferenceDataViewSet(
    WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet
):
    """Indicator-denominator reference data: catchment, ambulances, commodities (SET-006).

    The list defaults to *active* rows only, optionally narrowed by ``?kind=``:
    deactivated rows (SET-011) stay in the table — audit history and locked
    indicator periods keep pointing at them — but leave the default surface.
    DELETE is the deactivate verb: it flips ``active`` off and records an
    AUD-001 ``delete`` event (SET-012) instead of removing the row, so the
    audit trail outlives the row's presence in the wizard. PUT/PATCH are not
    routed: the interface is GET/POST/DELETE(deactivate), and a writable
    ``active`` flag is refused at the serializer anyway (see
    ``ReferenceDataSerializer``), which is why re-activation has no path.

    Writes are gated on the ``identity.reference_data.write`` claim via
    ``WritePermissionMixin``; reads stay authorised by authentication plus
    tenant scoping like every other tenant-owned resource. A duplicate
    ``(tenant_id, kind, key)`` is a state conflict answered 409 — checked
    against the tenant-scoped queryset first, with the unique constraint as
    the race guard.
    """

    serializer_class = ReferenceDataSerializer
    queryset = ReferenceData.objects.all()
    write_permission = "identity.reference_data.write"
    #: GET/POST/DELETE only; see the docstring for why PUT/PATCH never route.
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset().filter(active=True)
        kind = self.request.query_params.get("kind")
        if kind:
            # The kind enum was validated on write, so a filter here cannot
            # match a stored value outside it; the filter is a narrowing, not
            # a validation point.
            queryset = queryset.filter(kind=kind)
        return queryset

    def create(self, request, *args, **kwargs):
        """A duplicate ``(kind, key)`` in this tenant answers 409, not 400/500.

        The check runs against the *tenant-scoped* queryset: uniqueness is a
        ``(tenant_id, kind, key)`` constraint, so another hospital's identical
        key is not this tenant's conflict (the constraint, not a global
        UniqueValidator, is what enforces that). The check deliberately does
        not filter ``active`` — the constraint does not either, so a
        deactivated row blocks its own re-POST the same way (re-activation is
        not part of the interface). Excepting IntegrityError mirrors the
        onboarding endpoint's duplicate-slug handling — a race between the
        pre-check and the insert lands the same 409 instead of a 500.
        """
        tenant_id = self.get_tenant_id()
        if not tenant_id:
            raise PermissionDenied(TENANT_REQUIRED_MESSAGE)
        kind = request.data.get("kind")
        key = request.data.get("key")
        if ReferenceData.objects.filter(
            tenant_id=tenant_id, kind=kind, key=key
        ).exists():
            return Response(
                {
                    "detail": (
                        f"Reference data '{key}' of kind '{kind}' already "
                        "exists in this tenant."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            # Lost race: the unique (tenant_id, kind, key) constraint fired
            # between the pre-check and the insert.
            return Response(
                {
                    "detail": (
                        f"Reference data '{key}' of kind '{kind}' already "
                        "exists in this tenant."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

    def destroy(self, request, pk=None):
        """Deactivate, never hard-delete (SET-011).

        ``self.get_object()`` resolves through the tenant-scoped queryset, so
        a foreign or unknown id answers 404 before any write. The row keeps
        its data and its audit history; only its ``active`` flag flips, which
        is what removes it from the default list. The audit event uses the
        ``delete`` action (AUD-001) because that is the semantic the caller
        invoked, matching the mixin's ``perform_destroy`` convention.
        """
        instance = self.get_object()
        instance.active = False
        instance.save(update_fields=["active"])
        self._write_audit_log(instance, "delete")
        return Response(status=status.HTTP_204_NO_CONTENT)


class BaselineInputViewSet(
    WritePermissionMixin, TenantScopedQuerysetMixin, viewsets.ModelViewSet
):
    """Baseline/manual indicator inputs collected by the wizard (SET-007).

    GET lists the tenant's filed inputs; POST files one for an
    indicator-source code and period. The interface is deliberately
    GET/POST-only: a baseline value files a locked reporting period, and
    silent edits or hard deletes would divorce the stored number from the
    audit trail that justifies it (SET-010 later closes periods against these
    rows). Writes are gated on the ``identity.baseline_input.write`` claim;
    the serializer rejects negative values before any row is written.
    """

    serializer_class = BaselineInputSerializer
    queryset = BaselineInput.objects.all()
    write_permission = "identity.baseline_input.write"
    http_method_names = ["get", "post", "head", "options"]
