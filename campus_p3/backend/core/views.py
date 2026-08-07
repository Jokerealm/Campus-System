from drf_spectacular.utils import OpenApiExample, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.views import APIView

from .responses import api_response


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        responses=inline_serializer(
            name="HealthCheckResponse",
            fields={
                "request_id": serializers.CharField(allow_null=True),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="HealthCheckData",
                    fields={"status": serializers.CharField()},
                ),
            },
        ),
        examples=[
            OpenApiExample(
                "Success",
                value={
                    "request_id": None,
                    "code": "OK",
                    "message": "success",
                    "data": {"status": "ok"},
                },
            )
        ],
    )
    def get(self, request):
        return api_response(request, data={"status": "ok"})
