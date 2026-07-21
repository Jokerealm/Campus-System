from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler


class ConflictError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "resource state conflict"
    default_code = "CONFLICT"


class FileTooLargeError(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = "uploaded file is too large"
    default_code = "FILE_TOO_LARGE"


class UnsupportedFileTypeError(APIException):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    default_detail = "uploaded file type is not supported"
    default_code = "UNSUPPORTED_FILE_TYPE"


class AIResultNeedsReviewError(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "AI result requires human review"
    default_code = "AI_RESULT_NEEDS_REVIEW"


class AIServiceUnavailableError(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "AI service is unavailable"
    default_code = "AI_SERVICE_UNAVAILABLE"


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    request = context.get("request")

    if response is None:
        return _error_response(
            request=request,
            code="INTERNAL_ERROR",
            message="internal server error",
            data={},
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = _get_error_code(exc)
    if code == "UNAUTHORIZED":
        response.status_code = status.HTTP_401_UNAUTHORIZED
    response.data = {
        "request_id": getattr(request, "request_id", None),
        "code": code,
        "message": _get_error_message(exc),
        "data": _get_error_data(response.data),
    }
    return response


def _get_error_code(exc):
    if isinstance(exc, ValidationError):
        return "VALIDATION_ERROR"
    if isinstance(exc, NotAuthenticated):
        return "UNAUTHORIZED"
    if isinstance(exc, PermissionDenied):
        return "FORBIDDEN"
    if isinstance(exc, (NotFound, Http404)):
        return "NOT_FOUND"
    if isinstance(exc, ConflictError):
        return "CONFLICT"
    if isinstance(exc, APIException):
        default_code = getattr(exc, "default_code", None)
        if isinstance(default_code, str):
            return default_code.upper()
    return "INTERNAL_ERROR"


def _get_error_message(exc):
    detail = getattr(exc, "detail", None)
    if isinstance(detail, (list, dict)):
        return "validation error" if isinstance(exc, ValidationError) else str(detail)
    if detail is not None:
        return str(detail)
    return str(exc)


def _get_error_data(data):
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    return {"detail": data}


def _error_response(request, code, message, data, http_status):
    return Response(
        {
            "request_id": getattr(request, "request_id", None),
            "code": code,
            "message": message,
            "data": data,
        },
        status=http_status,
    )
