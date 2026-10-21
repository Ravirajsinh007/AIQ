from rest_framework import permissions
from apps.accounts.models import RoleChoices, MembershipStatus


def can_access_institute(user, institute_id):
    if user.is_platform_admin:
        return True
    return user.memberships.filter(
        institute_id=institute_id,
        role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.TEACHER, RoleChoices.EXAM_STAFF],
        status=MembershipStatus.ACTIVE,
    ).exists()


class CanManageSourceMaterials(permissions.BasePermission):
    """
    Role-based and tenant-scoped permission for Source Material document management:
    - Platform Admin: Full access.
    - Institute Admin & Exam Staff: Full access within own institute.
    - Teachers: Allowed within own institute.
    - Students: Strictly forbidden.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            return True

        # Students strictly denied
        has_student_only = (
            request.user.memberships.filter(role=RoleChoices.STUDENT, status=MembershipStatus.ACTIVE).exists()
            and not request.user.memberships.filter(
                role__in=[RoleChoices.TEACHER, RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
                status=MembershipStatus.ACTIVE
            ).exists()
        )
        if has_student_only:
            return False

        return request.user.memberships.filter(
            role__in=[RoleChoices.TEACHER, RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            status=MembershipStatus.ACTIVE
        ).exists()

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            return True

        institute_id = getattr(obj, 'institute_id', None)
        if not institute_id and hasattr(obj, 'document'):
            institute_id = obj.document.institute_id

        return request.user.memberships.filter(
            institute_id=institute_id,
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.TEACHER, RoleChoices.EXAM_STAFF],
            status=MembershipStatus.ACTIVE
        ).exists()


class CanGenerateQuestions(permissions.BasePermission):
    """
    Permission for triggering and reviewing AI question generation jobs:
    - Platform Admin: Full access.
    - Institute Admin, Exam Staff, Teachers: Allowed within their institute.
    - Students: Strictly forbidden.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            return True

        has_student_only = (
            request.user.memberships.filter(role=RoleChoices.STUDENT, status=MembershipStatus.ACTIVE).exists()
            and not request.user.memberships.filter(
                role__in=[RoleChoices.TEACHER, RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
                status=MembershipStatus.ACTIVE
            ).exists()
        )
        if has_student_only:
            return False

        return request.user.memberships.filter(
            role__in=[RoleChoices.TEACHER, RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            status=MembershipStatus.ACTIVE
        ).exists()

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            return True

        institute_id = getattr(obj, 'institute_id', None)
        if not institute_id and hasattr(obj, 'job'):
            institute_id = obj.job.institute_id

        return request.user.memberships.filter(
            institute_id=institute_id,
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.TEACHER, RoleChoices.EXAM_STAFF],
            status=MembershipStatus.ACTIVE
        ).exists()
