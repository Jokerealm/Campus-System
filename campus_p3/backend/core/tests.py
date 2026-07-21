from django.test import TestCase, override_settings
from django.urls import path
from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied, ValidationError
from rest_framework.test import APIClient
from rest_framework.views import APIView

from .authentication import MockHeaderAuthentication
from .exceptions import (
    AIResultNeedsReviewError,
    AIServiceUnavailableError,
    ConflictError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from .permissions import IsMockAuthenticated
from .responses import api_response
from .views import HealthCheckView


class TestErrorView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, error_code):
        errors = {
            "validation": ValidationError({"field": ["field is required"]}),
            "unauthorized": NotAuthenticated("authentication credentials were not provided"),
            "forbidden": PermissionDenied("permission denied"),
            "not-found": NotFound("resource not found"),
            "conflict": ConflictError("resource state conflict"),
            "file-too-large": FileTooLargeError(),
            "unsupported-file-type": UnsupportedFileTypeError(),
            "ai-needs-review": AIResultNeedsReviewError(),
            "ai-unavailable": AIServiceUnavailableError(),
            "internal": RuntimeError("unexpected error"),
        }
        error = errors.get(error_code)
        if error is None:
            raise NotFound("test error code not found")
        raise error


class TestIdentityView(APIView):
    authentication_classes = [MockHeaderAuthentication]
    permission_classes = [IsMockAuthenticated]

    def get(self, request):
        return api_response(
            request,
            data={
                "role": request.user.role,
                "identifier": request.user.identifier,
                "tenant_id": request.user.tenant_id,
            },
        )


urlpatterns = [
    path("api/health/", HealthCheckView.as_view()),
    path("api/health/test-identity/", TestIdentityView.as_view()),
    path("api/health/test-errors/<slug:error_code>/", TestErrorView.as_view()),
]


@override_settings(ROOT_URLCONF=__name__)
class ApiResponseTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_response_uses_standard_shape_and_request_id_header(self):
        response = self.client.get("/api/health/", HTTP_X_REQUEST_ID="req_test_001")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Request-Id"], "req_test_001")
        self.assertEqual(
            response.json(),
            {
                "request_id": "req_test_001",
                "code": "OK",
                "message": "success",
                "data": {"status": "ok"},
            },
        )

    def test_request_id_is_generated_when_header_is_missing(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["request_id"].startswith("req_"))
        self.assertEqual(response["X-Request-Id"], response.json()["request_id"])

    def test_validation_error_uses_standard_shape(self):
        response = self.client.get("/api/health/test-errors/validation/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("request_id", response.json())
        self.assertIn("field", response.json()["data"])

    def test_unauthorized_error_uses_standard_shape(self):
        response = self.client.get("/api/health/test-errors/unauthorized/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "UNAUTHORIZED")

    def test_forbidden_error_uses_standard_shape(self):
        response = self.client.get("/api/health/test-errors/forbidden/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "FORBIDDEN")

    def test_not_found_error_uses_standard_shape(self):
        response = self.client.get("/api/health/test-errors/not-found/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "NOT_FOUND")

    def test_conflict_error_uses_standard_shape(self):
        response = self.client.get("/api/health/test-errors/conflict/")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "CONFLICT")

    def test_internal_error_uses_standard_shape(self):
        response = self.client.get("/api/health/test-errors/internal/")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], "INTERNAL_ERROR")
        self.assertEqual(response.json()["message"], "internal server error")

    def test_student_workflow_error_codes_use_standard_shape(self):
        cases = [
            ("file-too-large", 413, "FILE_TOO_LARGE"),
            ("unsupported-file-type", 415, "UNSUPPORTED_FILE_TYPE"),
            ("ai-needs-review", 422, "AI_RESULT_NEEDS_REVIEW"),
            ("ai-unavailable", 503, "AI_SERVICE_UNAVAILABLE"),
        ]
        for path_value, expected_status, expected_code in cases:
            with self.subTest(code=expected_code):
                response = self.client.get(
                    f"/api/health/test-errors/{path_value}/"
                )
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json()["code"], expected_code)

    def test_mock_identity_requires_an_identity_header(self):
        response = self.client.get("/api/health/test-identity/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "UNAUTHORIZED")

    def test_mock_teacher_identity_uses_default_tenant(self):
        response = self.client.get(
            "/api/health/test-identity/",
            HTTP_X_TEACHER_ID="teacher_001",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            {
                "role": "teacher",
                "identifier": "teacher_001",
                "tenant_id": "default",
            },
        )

    def test_mock_service_identity_records_explicit_tenant(self):
        response = self.client.get(
            "/api/health/test-identity/",
            HTTP_X_SERVICE_ID="p2-service",
            HTTP_X_TENANT_ID="school_001",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            {
                "role": "service",
                "identifier": "p2-service",
                "tenant_id": "school_001",
            },
        )

    def test_mock_identity_rejects_multiple_identity_headers(self):
        response = self.client.get(
            "/api/health/test-identity/",
            HTTP_X_TEACHER_ID="teacher_001",
            HTTP_X_SERVICE_ID="p2-service",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "UNAUTHORIZED")

    def test_mock_identity_rejects_oversized_identity_and_tenant(self):
        identity_response = self.client.get(
            "/api/health/test-identity/",
            HTTP_X_STUDENT_ID="s" * 65,
        )
        tenant_response = self.client.get(
            "/api/health/test-identity/",
            HTTP_X_STUDENT_ID="stu_001",
            HTTP_X_TENANT_ID="t" * 65,
        )
        self.assertEqual(identity_response.status_code, 401)
        self.assertEqual(tenant_response.status_code, 401)
