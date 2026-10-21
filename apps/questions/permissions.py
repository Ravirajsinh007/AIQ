from rest_framework import permissions
from apps.accounts.models import RoleChoices, MembershipStatus


class CanManageQuestions(permissions.BasePermission):
    """
    Role-based and tenant-scoped permission for Question Bank management:
    - Platform Admin: Full access across all institutes.
    - Institute Admin: Full access within their institute.
    - Teachers: Can create and view questions for their assigned subjects in their institute;
      can edit their own questions while in 'draft' status.
    - Students: Denied access to authoring or viewing draft question bank items.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            return True

        # Students are strictly blocked from question bank authoring/browsing
        has_student_only = (
            request.user.memberships.filter(role=RoleChoices.STUDENT, status=MembershipStatus.ACTIVE).exists()
            and not request.user.memberships.filter(
                role__in=[RoleChoices.TEACHER, RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
                status=MembershipStatus.ACTIVE
            ).exists()
        )
        if has_student_only:
            return False

        # Must have an active teacher, exam_staff, or institute_admin membership
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
        if not institute_id and hasattr(obj, 'question'):
            institute_id = obj.question.institute_id

        # Verify membership in this institute
        membership = request.user.memberships.filter(
            institute_id=institute_id,
            role__in=[RoleChoices.TEACHER, RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            status=MembershipStatus.ACTIVE
        ).first()

        if not membership:
            return False

        # Institute Admins and Exam Staff have full operational access in their institute
        if membership.role in [RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF]:
            return True

        if membership.role != RoleChoices.TEACHER:
            return False

        if request.method in permissions.SAFE_METHODS:
            return True

        # Teachers can edit/modify questions they authored while in draft or rejected status
        if hasattr(obj, 'created_by') and obj.created_by == request.user:
            if obj.status in ['draft', 'rejected', 'under_review']:
                return True

        return False
