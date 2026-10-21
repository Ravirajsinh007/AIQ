from rest_framework import permissions
from .models import RoleChoices, MembershipStatus


class IsPlatformAdmin(permissions.BasePermission):
    """
    Grants access only to Platform Administrators and superusers.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_platform_admin


class IsInstituteAdmin(permissions.BasePermission):
    """
    Grants access only to Institute Administrators for their specific institute,
    or Platform Administrators.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            return True

        institute_id = view.kwargs.get('institute_id')
        if not institute_id:
            return False

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

        # If checking an Institute object
        institute_id = getattr(obj, 'institute_id', getattr(obj, 'id', None))
        return request.user.memberships.filter(
            institute_id=institute_id,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        ).exists()


class IsInstituteMember(permissions.BasePermission):
    """
    Grants access to any active member of the given institute, or Platform Admin.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_platform_admin:
            return True

        institute_id = view.kwargs.get('institute_id')
        if not institute_id:
            return False

        return request.user.memberships.filter(
            institute_id=institute_id,
            status=MembershipStatus.ACTIVE
        ).exists()


class EnforcePasswordChange(permissions.BasePermission):
    """
    Restricts users who must change their password from performing protected actions
    until their initial password change is completed.
    """
    message = "First-login password change is required before accessing application features."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return True
        return not request.user.must_change_password
