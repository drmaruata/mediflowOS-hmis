from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["POST"])
def trigger_indicator_compute(request):
    from workers.celery import compute_indicators
    tenant_id = request.data.get("tenant_id")
    period_start = request.data.get("period_start")
    period_end = request.data.get("period_end")
    compute_indicators.delay(tenant_id, period_start, period_end)
    return Response({"status": "queued"})
