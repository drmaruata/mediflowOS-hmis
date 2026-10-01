from django.urls import path
from rest_framework.decorators import api_view
from rest_framework.response import Response

app_name = "common"


@api_view(["GET"])
def health_check(request):
    return Response({"status": "ok", "version": "0.1.0"})


urlpatterns = [path("", health_check, name="health")]
