from rest_framework.response import Response


def api_response(request, data=None, code="OK", message="success", status=200):
    return Response(
        {
            "request_id": getattr(request, "request_id", None),
            "code": code,
            "message": message,
            "data": data if data is not None else {},
        },
        status=status,
    )
