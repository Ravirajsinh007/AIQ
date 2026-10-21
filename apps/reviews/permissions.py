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

        user_membership = request.user.memberships.filter(
            institute_id=institute_id,
            role__in=[RoleChoices.TEACHER, RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            status=MembershipStatus.ACTIVE
        ).first()

        if not user_membership:
            return False

        # Read-only safe methods
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write/review actions
        if user_membership.role in [RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF]:
            return True

        if user_membership.role == RoleChoices.TEACHER:
            return True

        return False
