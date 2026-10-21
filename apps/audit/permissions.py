from rest_framework.permissions import BasePermission

from apps.accounts.models import MembershipStatus, RoleChoices


class CanReadAuditEvents(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (
                user.is_platform_admin
                or user.memberships.filter(
                    role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
                    status=MembershipStatus.ACTIVE,
                ).exists()
            )
        )
