from django.urls import path
from .views import (
    LoginView,
    TokenRefreshView,
    LogoutView,
    CurrentUserView,
    PasswordChangeView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    AccountVerificationVerifyView,
    AccountActivationCompleteView,
    InstituteListCreateView,
    InstituteDetailView,
    PlatformDashboardOverviewView,
    ProvisionAdminView,
    InstituteMemberListCreateView,
    InstituteMemberDetailView,
    InstituteMemberDeactivateView,
    BulkImportUploadView,
    BulkImportDetailView,
    BulkImportPreviewView,
    BulkImportConfirmView,
)

urlpatterns = [
    # Auth endpoints (/api/v1/auth/...)
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='auth-token-refresh'),
    path('auth/logout/', LogoutView.as_view(), name='auth-logout'),
    path('auth/me/', CurrentUserView.as_view(), name='auth-me'),
    path('auth/password/change/', PasswordChangeView.as_view(), name='auth-password-change'),
    path('auth/password-reset/request/', PasswordResetRequestView.as_view(), name='auth-password-reset-request'),
    path('auth/password-reset/confirm/', PasswordResetConfirmView.as_view(), name='auth-password-reset-confirm'),
    path('auth/activation/verify/', AccountVerificationVerifyView.as_view(), name='auth-activation-verify'),
    path('auth/activation/complete/', AccountActivationCompleteView.as_view(), name='auth-activation-complete'),

    # Institute management (/api/v1/institutes/...)
    path('institutes/', InstituteListCreateView.as_view(), name='institute-list-create'),
    path('institutes/<uuid:institute_id>/', InstituteDetailView.as_view(), name='institute-detail'),
    path('institutes/<uuid:institute_id>/provision-admin/', ProvisionAdminView.as_view(), name='institute-provision-admin'),
    path('platform/dashboard/overview/', PlatformDashboardOverviewView.as_view(), name='platform-dashboard-overview'),

    # Institute members (/api/v1/institutes/{institute_id}/members/...)
    path('institutes/<uuid:institute_id>/members/', InstituteMemberListCreateView.as_view(), name='institute-members-list-create'),
    path('institutes/<uuid:institute_id>/members/<uuid:membership_id>/', InstituteMemberDetailView.as_view(), name='institute-member-detail'),
    path('institutes/<uuid:institute_id>/members/<uuid:membership_id>/deactivate/', InstituteMemberDeactivateView.as_view(), name='institute-member-deactivate'),

    # Bulk CSV/Excel imports (/api/v1/institutes/{institute_id}/imports/...)
    path('institutes/<uuid:institute_id>/imports/', BulkImportUploadView.as_view(), name='institute-import-upload'),
    path('institutes/<uuid:institute_id>/imports/<uuid:job_id>/', BulkImportDetailView.as_view(), name='institute-import-detail'),
    path('institutes/<uuid:institute_id>/imports/<uuid:job_id>/preview/', BulkImportPreviewView.as_view(), name='institute-import-preview'),
    path('institutes/<uuid:institute_id>/imports/<uuid:job_id>/confirm/', BulkImportConfirmView.as_view(), name='institute-import-confirm'),
]
