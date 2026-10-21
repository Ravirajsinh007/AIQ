from rest_framework.permissions import BasePermission

from apps.accounts.models import MembershipStatus, RoleChoices


MANAGER_ROLES = (RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF)
EXAM_MANAGER_PERMISSIONS = {'controller', 'exam_admin', 'exam_manager'}


def is_exam_manager(user, institute_id):
    if not user or not user.is_authenticated:
        return False
    if user.is_platform_admin:
        return True
    memberships = user.memberships.filter(
        institute_id=institute_id, status=MembershipStatus.ACTIVE, role__in=MANAGER_ROLES
    )
    return any(
        membership.role == RoleChoices.INSTITUTE_ADMIN
        or bool(set(membership.exam_permissions or []) & EXAM_MANAGER_PERMISSIONS)
        for membership in memberships
    )


class IsExamManager(BasePermission):
    def has_object_permission(self, request, view, obj):
        institute_id = getattr(obj, 'institute_id', None)
        if institute_id is None and hasattr(obj, 'exam'):
            institute_id = obj.exam.institute_id
        return is_exam_manager(request.user, institute_id)
