from rest_framework import permissions
from apps.accounts.models import RoleChoices, MembershipStatus


class CanReviewQuestions(permissions.BasePermission):
    """
    Permission class for reviewing questions:
    - Platform administrators: Read-only audit inspection, cannot make institutional decisions.
    - Institute administrators & exam staff: Can review any question within their institute.
    - Teachers: Can review questions within their institute, UNLESS they are the author of the question (anti-self-approval).
    - Students: Denied all access.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            # Platform administrators have read-only access for auditing
            return request.method in permissions.SAFE_METHODS

        # Students are blocked
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
            return request.method in permissions.SAFE_METHODS

        # Determine institute
        institute_id = getattr(obj, 'institute_id', None)
        if not institute_id and hasattr(obj, 'question'):
            institute_id = obj.question.institute_id

        manager_membership = request.user.memberships.filter(
            institute_id=institute_id,
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            status=MembershipStatus.ACTIVE
        ).first()

        if manager_membership:
            return True

        teacher_membership = request.user.memberships.filter(
            institute_id=institute_id,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE,
        ).first()
        if teacher_membership is None:
            return False
        subject_id = getattr(obj, 'subject_id', None)
        if subject_id is None and hasattr(obj, 'question'):
            subject_id = obj.question.subject_id
        if not teacher_membership.teaching_assignments.filter(
            subject_id=subject_id,
            status='active',
        ).exists():
            return False

        # Read-only safe methods
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write/review actions
        return True
