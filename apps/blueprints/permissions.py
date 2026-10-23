from rest_framework import permissions
from apps.accounts.models import RoleChoices, MembershipStatus


class CanManageBlueprints(permissions.BasePermission):
    """
    Role-based and tenant-scoped permission for Examination Blueprints and Paper Generation:
    - Platform Admin: Read-only audit access across institutes; cannot generate papers on behalf of institutes.
    - Institute Admin & Exam Staff: Full management of blueprints and papers within their institute.
    - Teachers: Can create, view, edit blueprints, and generate papers ONLY within their institute
      and for subjects they are actively assigned to teach.
    - Students: Strictly forbidden from accessing blueprint and paper generation endpoints.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            return request.method in permissions.SAFE_METHODS

        # Block students completely
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

        institute_id = getattr(obj, 'institute_id', None)
        if not institute_id and hasattr(obj, 'blueprint'):
            institute_id = obj.blueprint.institute_id
        if not institute_id and hasattr(obj, 'section'):
            institute_id = obj.section.blueprint.institute_id

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
        if membership is not None:
            subject = getattr(obj, 'subject', None)
            if not subject and hasattr(obj, 'blueprint'):
                subject = obj.blueprint.subject
            if not subject and hasattr(obj, 'section'):
                subject = obj.section.blueprint.subject

            if subject:
                # Must be actively assigned to this subject
                is_assigned = membership.teaching_assignments.filter(
                    subject=subject,
                    status='active'
                ).exists()
                return is_assigned

            return False

        return False
