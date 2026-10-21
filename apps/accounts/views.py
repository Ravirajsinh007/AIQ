from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView
from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import (
    Institute,
    User,
    UserInstituteMembership,
    RoleChoices,
    MembershipStatus,
    BulkImportJob,
    ImportStatus,
)
from .permissions import (
    IsPlatformAdmin,
    IsInstituteAdmin,
    IsInstituteMember,
    EnforcePasswordChange,
)
from .serializers import (
    LoginSerializer,
    UserSerializer,
    PasswordChangeSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    AccountVerificationVerifySerializer,
    AccountActivationCompleteSerializer,
    InstituteSerializer,
    ProvisionAdminSerializer,
    UserInstituteMembershipSerializer,
    MembershipUpdateSerializer,
    CreateMemberSerializer,
    BulkImportJobSerializer,
    BulkImportJobDetailSerializer,
)
from .services import BulkImportService


# ==============================================================================
# Authentication & Account Lifecycle Views
# ==============================================================================

class LoginView(APIView):
    """
    Authenticates user with email and password.
    Returns JWT access and refresh tokens, user profile, and first-login password enforcement flag.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="User Login",
        request=LoginSerializer,
        responses={200: OpenApiResponse(description="Login successful, tokens returned")}
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class TokenRefreshView(BaseTokenRefreshView):
    """
    Refreshes expired access tokens using a valid refresh token.
    """
    @extend_schema(summary="Refresh JWT Token")
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class LogoutView(APIView):
    """
    Invalidates the active refresh token by adding it to the token blacklist.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="User Logout",
        description="Blacklists the provided refresh token to revoke session."
    )
    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'error': {'message': 'Refresh token is required for logout.'}},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({'message': 'Logged out successfully.'}, status=status.HTTP_200_OK)
        except Exception:
            return Response(
                {'error': {'message': 'Invalid or expired refresh token.'}},
                status=status.HTTP_400_BAD_REQUEST
            )


class CurrentUserView(APIView):
    """
    Returns the authenticated user's profile and active institute memberships.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get Current User Profile",
        responses={200: UserSerializer}
    )
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PasswordChangeView(APIView):
    """
    Allows authenticated users to change their password.
    Clears the must_change_password flag upon completion.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Change Password",
        request=PasswordChangeSerializer,
        responses={200: OpenApiResponse(description="Password changed successfully")}
    )
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Password has been updated successfully.'}, status=status.HTTP_200_OK)


class PasswordResetRequestView(APIView):
    """
    Initiates a secure password reset workflow.
    Always returns a generic message to prevent email enumeration.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Request Password Reset",
        request=PasswordResetRequestSerializer,
        responses={200: OpenApiResponse(description="Instructions dispatched")}
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    """
    Completes password reset using single-use cryptographically hashed token.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Confirm Password Reset",
        request=PasswordResetConfirmSerializer,
        responses={200: OpenApiResponse(description="Password reset successful")}
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Password has been reset successfully. You can now log in.'}, status=status.HTTP_200_OK)


class AccountVerificationVerifyView(APIView):
    """
    Validates a 6-digit verification code.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Verify Activation Code",
        request=AccountVerificationVerifySerializer,
        responses={200: OpenApiResponse(description="Code is valid")}
    )
    def post(self, request):
        serializer = AccountVerificationVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({'message': 'Verification code is valid.'}, status=status.HTTP_200_OK)


class AccountActivationCompleteView(APIView):
    """
    Completes account onboarding by verifying the code and setting a personal password.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Complete Account Activation",
        request=AccountActivationCompleteSerializer,
        responses={200: OpenApiResponse(description="Account activated")}
    )
    def post(self, request):
        serializer = AccountActivationCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {'message': 'Account activated and password set successfully. You can now log in.'},
            status=status.HTTP_200_OK
        )


# ==============================================================================
# Institute Management Views
# ==============================================================================

class InstituteListCreateView(generics.ListCreateAPIView):
    """
    List institutes or create a new institute.
    Creation is strictly restricted to Platform Administrators.
    Listing returns institutes the user has active membership with (or all for Platform Admin).
    """
    serializer_class = InstituteSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsPlatformAdmin()]
        return [IsAuthenticated(), EnforcePasswordChange()]

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return Institute.objects.all().order_by('name')
        return Institute.objects.filter(
            memberships__user=user,
            memberships__status=MembershipStatus.ACTIVE
        ).distinct().order_by('name')

    @transaction.atomic
    def perform_create(self, serializer):
        institute = serializer.save()
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='institute.created',
            resource_type='institute',
            resource_id=institute.pk,
            actor=self.request.user,
        )

    @extend_schema(summary="List Institutes")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Create Institute (Platform Admin Only)")
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class InstituteDetailView(generics.RetrieveUpdateAPIView):
    """
    Retrieve or update institute details.
    Restricted to Platform Administrators or Institute Administrators for that institute.
    """
    serializer_class = InstituteSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'institute_id'

    def get_permissions(self):
        return [IsAuthenticated(), EnforcePasswordChange(), IsInstituteAdmin()]

    def get_queryset(self):
        return Institute.objects.all()

    @transaction.atomic
    def perform_update(self, serializer):
        institute = serializer.save()
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='institute.updated',
            resource_type='institute',
            resource_id=institute.pk,
            actor=self.request.user,
            institute=institute,
        )

    @extend_schema(summary="Get Institute Details")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Update Institute Details")
    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)


class ProvisionAdminView(APIView):
    """
    Provisions the first Institute Administrator for an institute.
    Strictly restricted to Platform Administrators.
    """
    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        summary="Provision Institute Administrator (Platform Admin Only)",
        request=ProvisionAdminSerializer,
        responses={201: OpenApiResponse(description="Institute Administrator provisioned")}
    )
    def post(self, request, institute_id):
        institute = get_object_or_404(Institute, id=institute_id)
        serializer = ProvisionAdminSerializer(data=request.data, context={'institute': institute})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            user, membership = serializer.save()
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='membership.admin_provisioned',
                resource_type='membership',
                resource_id=membership.pk,
                actor=request.user,
                institute=membership.institute,
                metadata={'role': membership.role},
            )
        return Response({
            'message': f"Institute Administrator provisioned successfully for {institute.name}.",
            'user': UserSerializer(user).data,
            'membership': UserInstituteMembershipSerializer(membership).data
        }, status=status.HTTP_201_CREATED)


# ==============================================================================
# Institute Membership & Roster Views
# ==============================================================================

class InstituteMemberListCreateView(APIView):
    """
    List members of an institute or onboard a new member (Teacher, Student, Exam Staff).
    Restricted to Institute Administrators of this institute or Platform Administrators.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, IsInstituteAdmin]

    @extend_schema(
        summary="List Institute Members",
        responses={200: UserInstituteMembershipSerializer(many=True)}
    )
    def get(self, request, institute_id):
        institute = get_object_or_404(Institute, id=institute_id)
        memberships = UserInstituteMembership.objects.filter(institute=institute).select_related('user', 'institute')

        # Filter by role
        role = request.query_params.get('role')
        if role:
            memberships = memberships.filter(role=role)

        # Filter by status
        status_param = request.query_params.get('status')
        if status_param:
            memberships = memberships.filter(status=status_param)

        # Search by email or name or identifier
        search = request.query_params.get('search')
        if search:
            memberships = memberships.filter(
                models.Q(user__email__icontains=search) |
                models.Q(user__first_name__icontains=search) |
                models.Q(user__last_name__icontains=search) |
                models.Q(identifier__icontains=search)
            )

        serializer = UserInstituteMembershipSerializer(memberships, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Add Institute Member (Teacher / Student / Exam Staff)",
        request=CreateMemberSerializer,
        responses={201: UserInstituteMembershipSerializer}
    )
    def post(self, request, institute_id):
        institute = get_object_or_404(Institute, id=institute_id)
        serializer = CreateMemberSerializer(data=request.data, context={'institute': institute})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            membership = serializer.save()
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='membership.created',
                resource_type='membership',
                resource_id=membership.pk,
                actor=request.user,
                institute=institute,
                metadata={'role': membership.role, 'membership_status': membership.status},
            )
        return Response(
            UserInstituteMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED
        )


class InstituteMemberDetailView(APIView):
    """
    Retrieve or update a member's role, status, or identifier.
    Restricted to Institute Administrators of this institute or Platform Administrators.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, IsInstituteAdmin]

    @extend_schema(summary="Get Member Details")
    def get(self, request, institute_id, membership_id):
        membership = get_object_or_404(
            UserInstituteMembership.objects.select_related('user', 'institute'),
            id=membership_id,
            institute_id=institute_id
        )
        return Response(UserInstituteMembershipSerializer(membership).data, status=status.HTTP_200_OK)

    @extend_schema(summary="Update Member Details")
    def patch(self, request, institute_id, membership_id):
        membership = get_object_or_404(
            UserInstituteMembership,
            id=membership_id,
            institute_id=institute_id
        )
        # Prevent escalating to Platform Admin
        new_role = request.data.get('role')
        if new_role == RoleChoices.PLATFORM_ADMIN and not request.user.is_platform_admin:
            return Response(
                {'error': {'message': 'Cannot assign Platform Administrator role.'}},
                status=status.HTTP_403_FORBIDDEN
            )

        forbidden_fields = {'user', 'institute', 'is_verified'} & set(request.data)
        if forbidden_fields:
            return Response(
                {'error': {'message': 'Membership user, institute, and verification state cannot be changed here.'}},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = MembershipUpdateSerializer(membership, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            membership = serializer.save()
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='membership.updated',
                resource_type='membership',
                resource_id=membership.pk,
                actor=request.user,
                institute=membership.institute,
                metadata={'role': membership.role, 'membership_status': membership.status},
            )
        return Response(
            UserInstituteMembershipSerializer(membership).data,
            status=status.HTTP_200_OK
        )


class InstituteMemberDeactivateView(APIView):
    """
    Deactivates a user's membership within an institute.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, IsInstituteAdmin]

    @extend_schema(summary="Deactivate Member")
    def post(self, request, institute_id, membership_id):
        membership = get_object_or_404(
            UserInstituteMembership,
            id=membership_id,
            institute_id=institute_id
        )
        with transaction.atomic():
            membership.status = MembershipStatus.INACTIVE
            membership.save(update_fields=['status', 'updated_at'])
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='membership.deactivated',
                resource_type='membership',
                resource_id=membership.pk,
                actor=request.user,
                institute=membership.institute,
                metadata={'membership_status': membership.status},
            )
        return Response({'message': 'Membership deactivated successfully.'}, status=status.HTTP_200_OK)


# ==============================================================================
# Bulk CSV / Excel Import Views
# ==============================================================================

class BulkImportUploadView(APIView):
    """
    Uploads a CSV or Excel file of students or teachers for validation.
    Runs automated schema validation, email verification, and duplicate detection.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, IsInstituteAdmin]

    @extend_schema(
        summary="Upload Bulk User Roster (CSV / XLSX)",
        responses={201: BulkImportJobDetailSerializer}
    )
    def post(self, request, institute_id):
        institute = get_object_or_404(Institute, id=institute_id)
        uploaded_file = request.FILES.get('file')
        import_type = request.data.get('import_type', 'students')

        if not uploaded_file:
            return Response(
                {'error': {'message': 'No file uploaded. Please upload a CSV or XLSX file.'}},
                status=status.HTTP_400_BAD_REQUEST
            )

        if import_type not in ['students', 'teachers']:
            return Response(
                {'error': {'message': "Invalid import_type. Must be 'students' or 'teachers'."}},
                status=status.HTTP_400_BAD_REQUEST
            )

        job = BulkImportJob.objects.create(
            institute=institute,
            import_type=import_type,
            file_name=uploaded_file.name,
            initiated_by=request.user,
            status=ImportStatus.UPLOADED
        )

        # Run parsing & validation service
        job = BulkImportService.parse_and_validate(job, uploaded_file)
        return Response(BulkImportJobDetailSerializer(job).data, status=status.HTTP_201_CREATED)


class BulkImportDetailView(APIView):
    """
    Returns import job status and summary.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, IsInstituteAdmin]

    @extend_schema(summary="Get Import Job Summary")
    def get(self, request, institute_id, job_id):
        job = get_object_or_404(BulkImportJob, id=job_id, institute_id=institute_id)
        return Response(BulkImportJobDetailSerializer(job).data, status=status.HTTP_200_OK)


class BulkImportPreviewView(APIView):
    """
    Previews valid candidate records and row-level errors for an import job.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, IsInstituteAdmin]

    @extend_schema(summary="Preview Import Records")
    def get(self, request, institute_id, job_id):
        job = get_object_or_404(BulkImportJob, id=job_id, institute_id=institute_id)
        return Response({
            'job_id': str(job.id),
            'status': job.status,
            'total_rows': job.total_rows,
            'valid_rows': job.valid_rows,
            'error_rows': job.error_rows,
            'valid_candidates_preview': job.parsed_data[:50],  # Preview first 50
            'errors': [
                {
                    'row': err.row_number,
                    'field': err.field_name,
                    'code': err.error_code,
                    'message': err.error_message,
                    'raw': err.raw_data
                }
                for err in job.row_errors.all()
            ]
        }, status=status.HTTP_200_OK)


class BulkImportConfirmView(APIView):
    """
    Confirms an import job and commits valid records to the database.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, IsInstituteAdmin]

    @extend_schema(summary="Confirm and Execute Bulk Import")
    def post(self, request, institute_id, job_id):
        job = get_object_or_404(BulkImportJob, id=job_id, institute_id=institute_id)
        if job.status != ImportStatus.VALIDATED:
            return Response(
                {'error': {'message': f"Job cannot be confirmed in current status: {job.status}."}},
                status=status.HTTP_400_BAD_REQUEST
            )

        created_count = BulkImportService.confirm_import(job)
        return Response({
            'message': f"Bulk import confirmed successfully. Created {created_count} members.",
            'job': BulkImportJobSerializer(job).data
        }, status=status.HTTP_200_OK)
