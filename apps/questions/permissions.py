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
        manager_membership = request.user.memberships.filter(
            institute_id=institute_id,
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            status=MembershipStatus.ACTIVE
        ).first()

        if manager_membership:
            return True

        membership = request.user.memberships.filter(
            institute_id=institute_id,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE,
        ).first()
        if membership is None:
            return False
        subject_id = getattr(obj, 'subject_id', None)
        if subject_id is None and hasattr(obj, 'question'):
            subject_id = obj.question.subject_id
        if not membership.teaching_assignments.filter(
            subject_id=subject_id,
            status='active',
        ).exists():
            return False

        if request.method in permissions.SAFE_METHODS:
            return True

        # Teachers can edit/modify questions they authored while in draft or rejected status
        if hasattr(obj, 'created_by') and obj.created_by == request.user:
            if obj.status in ['draft', 'rejected', 'under_review']:
                return True

        return False
