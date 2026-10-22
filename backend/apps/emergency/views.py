"""Emergency views."""
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from common.tenant import TenantScopedQuerysetMixin
from .models import Triage
from .serializers import TriageSerializer

#: Refusal for a request that names two different triage categories through the
#: two spellings below. Named so a client — and the test suite — can match the
#: contract rather than the prose, and so the two names can never drift apart.
FILTER_CONFLICT_MESSAGE = (
    "category and status name different triage categories. 'status' "
    "is an alias for 'category' on this board; supply one or the "
    "other, not two different values."
)


class TriageViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = TriageSerializer
    queryset = Triage.objects.all()

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise PermissionDenied("A tenant must be resolved.")
        serializer.save(**{"tenant_id": tenant_id})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "category",
                str,
                description=(
                    "Triage category to show (I, II, III, IV or V). This is the "
                    "column on the model and the parameter's real name."
                ),
            ),
            OpenApiParameter(
                "status",
                str,
                description=(
                    "Alias for 'category', kept because the OPD token queue "
                    "spells its filter 'status' and a client following that "
                    "convention across the boards must not meet a 500 here."
                ),
            ),
        ]
    )
    @action(detail=False, methods=["get"])
    def tracking_board(self, request):
        """ER tracking board — REST polling, not Channels (PLT-003, INT-013).

        Filtered on ``Triage.category``, the column that exists. The board used
        to filter on ``status``, which ``Triage`` does not have: its fields are
        ``tenant_id, patient_id, category, arrival_time,
        first_assessment_time, mlc_flag``. Filtering on a column that is not
        there raises ``FieldError`` out of the view, so every ``?status=``
        request answered 500 — a waiting-room board that broke the moment an ER
        nurse filtered it. ``apps/ipd/views.py``'s bed board docstring records
        the same mistake on ``facility_id``; this is that bug, second time.

        ``status`` is therefore accepted as a documented alias for ``category``
        rather than dropped: ``/api/v1/tokens/queue/`` filters on a real
        ``status`` column, and a client carrying that convention to a second
        board should get the rows it asked for, not a 500. Send both names
        with different values and the request contradicts itself — answered 400
        with a message naming the conflict, rather than silently preferring one
        and reporting a board the caller did not ask for.

        No value whitelist, on purpose: an unknown category yields an empty
        board, exactly as an unknown token status does on the queue board today.
        The column carries no ``choices``, so a list here would be a second
        source of truth that drifts the first time triage categories change.
        """
        category = request.query_params.get("category")
        alias = request.query_params.get("status")
        if category and alias and category != alias:
            raise ValidationError(FILTER_CONFLICT_MESSAGE)

        selected = category or alias
        queryset = self.get_queryset()
        if selected:
            queryset = queryset.filter(category=selected)

        return Response(TriageSerializer(queryset.order_by("-arrival_time"), many=True).data)
