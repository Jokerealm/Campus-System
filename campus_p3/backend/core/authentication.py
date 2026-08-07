from dataclasses import dataclass

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import NotAuthenticated


@dataclass(frozen=True, slots=True)
class MockIdentity:
    """Development-only identity populated from the P3 mock headers."""

    role: str
    identifier: str
    tenant_id: str = "default"

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False


class MockHeaderAuthentication(BaseAuthentication):
    """Authenticate exactly one teacher, service, or student request header."""

    identity_headers = (
        ("teacher", "X-Teacher-Id"),
        ("service", "X-Service-Id"),
        ("student", "X-Student-Id"),
    )

    def authenticate(self, request):
        identities = [
            (role, value)
            for role, header_name in self.identity_headers
            if (value := self._header_value(request, header_name))
        ]
        if not identities:
            return None
        if len(identities) > 1:
            raise NotAuthenticated("provide exactly one mock identity header")

        role, identifier = identities[0]
        tenant_id = self._header_value(request, "X-Tenant-Id") or "default"
        if len(identifier) > 64:
            raise NotAuthenticated("mock identity must contain at most 64 characters")
        if len(tenant_id) > 64:
            raise NotAuthenticated("X-Tenant-Id must contain at most 64 characters")
        identity = MockIdentity(
            role=role,
            identifier=identifier,
            tenant_id=tenant_id,
        )
        request.mock_identity = identity
        request.tenant_id = tenant_id
        return identity, None

    def authenticate_header(self, request):
        return "MockHeaders"

    @staticmethod
    def _header_value(request, header_name):
        return request.headers.get(header_name, "").strip()


class MockHeaderAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "core.authentication.MockHeaderAuthentication"
    name = ["teacherHeader", "serviceHeader", "studentHeader"]

    def get_security_requirement(self, auto_schema):
        from .permissions import IsStudent, IsTeacherOrService

        permission_types = {
            permission.__class__ for permission in auto_schema.view.get_permissions()
        }
        if IsTeacherOrService in permission_types:
            names = self.name[:2]
        elif IsStudent in permission_types:
            names = self.name[2:]
        else:
            names = self.name
        return [{name: []} for name in names]

    def get_security_definition(self, auto_schema):
        return [
            {
                "type": "apiKey",
                "in": "header",
                "name": header_name,
                "description": (
                    "Mock development identity. X-Tenant-Id is optional and defaults "
                    "to 'default'."
                ),
            }
            for _, header_name in MockHeaderAuthentication.identity_headers
        ]
