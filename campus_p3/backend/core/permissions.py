from rest_framework.permissions import BasePermission

from .authentication import MockIdentity


class IsMockAuthenticated(BasePermission):
    message = "a mock identity header is required"

    def has_permission(self, request, view):
        return isinstance(request.user, MockIdentity)


class IsTeacherOrService(BasePermission):
    message = "a teacher or service identity is required"

    def has_permission(self, request, view):
        return (
            isinstance(request.user, MockIdentity)
            and request.user.role in {"teacher", "service"}
        )


class IsStudent(BasePermission):
    message = "a student identity is required"

    def has_permission(self, request, view):
        return isinstance(request.user, MockIdentity) and request.user.role == "student"
