from rest_framework import permissions
from apps.accounts.models import RoleChoices, MembershipStatus


class IsInstituteAcademicAdmin(permissions.BasePermission):
    """
    Grants write/manage access to Institute Administrators for their own institute,
    and Platform Administrators.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            return True

        if request.method in permissions.SAFE_METHODS:
            return True

        institute_id = request.data.get('institute') or request.query_params.get('institute')
        if not institute_id:
            # Check user has any institute_admin role
            return request.user.memberships.filter(
                role=RoleChoices.INSTITUTE_ADMIN,
                status=MembershipStatus.ACTIVE
            ).exists()

        return request.user.memberships.filter(
            institute_id=institute_id,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        ).exists()

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            return True

        # Extract institute_id from obj
        institute_id = getattr(obj, 'institute_id', None)
        if not institute_id:
            if hasattr(obj, 'program'):
                institute_id = obj.program.institute_id
            elif hasattr(obj, 'batch'):
                institute_id = obj.batch.institute_id
            elif hasattr(obj, 'subject'):
                institute_id = obj.subject.institute_id
            elif hasattr(obj, 'unit'):
                institute_id = obj.unit.subject.institute_id
            elif hasattr(obj, 'teacher'):
                institute_id = obj.teacher.institute_id
            elif hasattr(obj, 'student'):
                institute_id = obj.student.institute_id

        if request.method in permissions.SAFE_METHODS:
            # Any active member of the institute can view
            return request.user.memberships.filter(
                institute_id=institute_id,
                status=MembershipStatus.ACTIVE
            ).exists()

        # Write operations strictly require Institute Admin role
        return request.user.memberships.filter(
            institute_id=institute_id,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        ).exists()
