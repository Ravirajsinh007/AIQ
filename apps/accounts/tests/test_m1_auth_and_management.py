import io
import openpyxl
from django.core import mail
from django.urls import reverse
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from apps.accounts.models import (
    User,
    Institute,
    UserInstituteMembership,
    RoleChoices,
    MembershipStatus,
    AccountVerification,
    PasswordResetRequest,
    BulkImportJob,
    ImportStatus,
    ImportType,
)
from apps.academics.models import Batch, Department, Program, Subject


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_HOST='smtp.example.test',
    DEFAULT_FROM_EMAIL='noreply@example.test',
)
class M1UserAndAccessManagementTests(APITestCase):

    def setUp(self):
        # 1. Platform Admin
        self.platform_admin = User.objects.create_superuser(
            email='superadmin@examcraft.org',
            password='PlatformAdminPassword123!',
            first_name='Platform',
            last_name='Admin'
        )

        # 2. Institute Alpha & Institute Beta
        self.institute_alpha = Institute.objects.create(
            code='ALPHA',
            name='Alpha Institute of Technology',
            status='active'
        )
        self.institute_beta = Institute.objects.create(
            code='BETA',
            name='Beta Global University',
            status='active'
        )

        # 3. Institute Alpha Admin
        self.alpha_admin = User.objects.create_user(
            email='admin@alpha.edu',
            password='AlphaAdminPass123!',
            first_name='Alice',
            last_name='Admin',
            is_verified=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.alpha_admin,
            institute=self.institute_alpha,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        )

        # 4. Institute Beta Admin
        self.beta_admin = User.objects.create_user(
            email='admin@beta.edu',
            password='BetaAdminPass123!',
            first_name='Bob',
            last_name='Admin',
            is_verified=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.beta_admin,
            institute=self.institute_beta,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        )

        # 5. Teacher in Alpha
        self.teacher_alpha = User.objects.create_user(
            email='teacher@alpha.edu',
            password='TeacherPass123!',
            first_name='Grace',
            last_name='Hopper',
            is_verified=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.teacher_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE
        )

        # 6. Student in Alpha
        self.student_alpha = User.objects.create_user(
            email='student@alpha.edu',
            password='StudentPass123!',
            first_name='Ada',
            last_name='Lovelace',
            is_verified=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.student_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.STUDENT,
            identifier='ROLL001',
            status=MembershipStatus.ACTIVE
        )
        self.department_alpha = Department.objects.create(
            institute=self.institute_alpha,
            code='CSE',
            name='Computer Science',
        )
        self.program_alpha = Program.objects.create(
            institute=self.institute_alpha,
            department=self.department_alpha,
            code='BTECH-CSE',
            name='Computer Science',
        )
        self.batch_alpha = Batch.objects.create(
            institute=self.institute_alpha,
            program=self.program_alpha,
            name='CSE 2026',
            admission_year=2026,
        )
        self.subject_alpha = Subject.objects.create(
            institute=self.institute_alpha,
            department=self.department_alpha,
            code='CS101',
            name='Programming Fundamentals',
        )

    # --------------------------------------------------------------------------
    # Authentication Tests
    # --------------------------------------------------------------------------

    def test_valid_login_returns_jwt_and_profile(self):
        url = reverse('auth-login')
        response = self.client.post(url, {
            'email': 'admin@alpha.edu',
            'password': 'AlphaAdminPass123!'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['user']['email'], 'admin@alpha.edu')
        self.assertFalse(response.data['user']['is_platform_admin'])
        self.assertFalse(response.data['must_change_password'])

    def test_platform_admin_login_identifies_superuser_without_membership(self):
        response = self.client.post(reverse('auth-login'), {
            'email': self.platform_admin.email,
            'password': 'PlatformAdminPassword123!'
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['user']['is_platform_admin'])
        self.assertEqual(response.data['user']['memberships'], [])

    def test_invalid_login_credentials_rejected(self):
        url = reverse('auth-login')
        response = self.client.post(url, {
            'email': 'admin@alpha.edu',
            'password': 'WrongPassword999!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data['error']['details']['non_field_errors'][0],
            'Invalid email or password.'
        )

    def test_deactivated_user_cannot_login(self):
        self.alpha_admin.is_active = False
        self.alpha_admin.save()
        url = reverse('auth-login')
        response = self.client.post(url, {
            'email': 'admin@alpha.edu',
            'password': 'AlphaAdminPass123!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_current_user_me_endpoint(self):
        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('auth-me')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'admin@alpha.edu')
        self.assertFalse(response.data['is_platform_admin'])
        self.assertEqual(len(response.data['memberships']), 1)
        self.assertEqual(response.data['memberships'][0]['institute_code'], 'ALPHA')

    def test_platform_admin_profile_requires_no_institute_membership(self):
        self.client.force_authenticate(user=self.platform_admin)
        response = self.client.get(reverse('auth-me'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_platform_admin'])
        self.assertEqual(response.data['memberships'], [])

    def test_logout_blacklists_refresh_token(self):
        login_url = reverse('auth-login')
        login_resp = self.client.post(login_url, {
            'email': 'admin@alpha.edu',
            'password': 'AlphaAdminPass123!'
        })
        refresh_token = login_resp.data['refresh']

        self.client.force_authenticate(user=self.alpha_admin)
        logout_url = reverse('auth-logout')
        response = self.client.post(logout_url, {'refresh': refresh_token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Refresh with blacklisted token should now fail
        refresh_url = reverse('auth-token-refresh')
        ref_resp = self.client.post(refresh_url, {'refresh': refresh_token})
        self.assertEqual(ref_resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # --------------------------------------------------------------------------
    # Password Lifecycle & Enforcement Tests
    # --------------------------------------------------------------------------

    def test_password_change_success_and_clears_must_change_flag(self):
        self.alpha_admin.must_change_password = True
        self.alpha_admin.save()

        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('auth-password-change')
        response = self.client.post(url, {
            'old_password': 'AlphaAdminPass123!',
            'new_password': 'BrandNewSecurePass2026!'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.alpha_admin.refresh_from_db()
        self.assertTrue(self.alpha_admin.check_password('BrandNewSecurePass2026!'))
        self.assertFalse(self.alpha_admin.must_change_password)

    def test_password_change_rejects_incorrect_old_password(self):
        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('auth-password-change')
        response = self.client.post(url, {
            'old_password': 'WrongOldPassword!',
            'new_password': 'BrandNewSecurePass2026!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_first_login_password_enforcement_blocks_protected_views(self):
        self.teacher_alpha.must_change_password = True
        self.teacher_alpha.save()

        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('institute-members-list-create', kwargs={'institute_id': self.institute_alpha.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_password_reset_request_and_confirm_workflow(self):
        req_url = reverse('auth-password-reset-request')
        req_resp = self.client.post(req_url, {'email': 'admin@alpha.edu'})
        self.assertEqual(req_resp.status_code, status.HTTP_200_OK)

        reset_obj = PasswordResetRequest.objects.filter(user=self.alpha_admin).order_by('-created_at').first()
        self.assertIsNotNone(reset_obj)

        test_obj, raw_token = PasswordResetRequest.create_request(user=self.alpha_admin)

        confirm_url = reverse('auth-password-reset-confirm')
        confirm_resp = self.client.post(confirm_url, {
            'email': 'admin@alpha.edu',
            'token': raw_token,
            'new_password': 'ResetSuccessPass123!'
        })
        self.assertEqual(confirm_resp.status_code, status.HTTP_200_OK)

        self.alpha_admin.refresh_from_db()
        self.assertTrue(self.alpha_admin.check_password('ResetSuccessPass123!'))

        reuse_resp = self.client.post(confirm_url, {
            'email': 'admin@alpha.edu',
            'token': raw_token,
            'new_password': 'AnotherNewPass123!'
        })
        self.assertEqual(reuse_resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_account_activation_complete_workflow(self):
        new_user = User.objects.create_user(
            email='onboarding@alpha.edu',
            first_name='New',
            last_name='Student',
            is_active=False,
            is_verified=False
        )
        new_user.set_unusable_password()
        new_user.save()

        verification, raw_code = AccountVerification.create_verification(
            user=new_user,
            purpose=AccountVerification.PURPOSE_ACTIVATION
        )

        # 1. Verify code
        verify_url = reverse('auth-activation-verify')
        ver_resp = self.client.post(verify_url, {
            'email': 'onboarding@alpha.edu',
            'code': raw_code
        })
        self.assertEqual(ver_resp.status_code, status.HTTP_200_OK)

        # 2. Complete activation with password setup
        complete_url = reverse('auth-activation-complete')
        comp_resp = self.client.post(complete_url, {
            'email': 'onboarding@alpha.edu',
            'code': raw_code,
            'new_password': 'StudentSecretPass123!'
        })
        self.assertEqual(comp_resp.status_code, status.HTTP_200_OK)

        new_user.refresh_from_db()
        self.assertTrue(new_user.is_active)
        self.assertTrue(new_user.is_verified)
        self.assertTrue(new_user.check_password('StudentSecretPass123!'))

        # Log in with newly activated credentials
        login_url = reverse('auth-login')
        log_resp = self.client.post(login_url, {
            'email': 'onboarding@alpha.edu',
            'password': 'StudentSecretPass123!'
        })
        self.assertEqual(log_resp.status_code, status.HTTP_200_OK)

    # --------------------------------------------------------------------------
    # Multi-Institute Isolation & Role Authorization Tests
    # --------------------------------------------------------------------------

    def test_platform_admin_can_create_institute(self):
        self.client.force_authenticate(user=self.platform_admin)
        url = reverse('institute-list-create')
        user_count_before = User.objects.count()
        membership_count_before = UserInstituteMembership.objects.count()
        response = self.client.post(url, {
            'code': 'GAMMA',
            'name': 'Gamma Institute of Science'
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['code'], 'GAMMA')
        self.assertEqual(User.objects.count(), user_count_before)
        self.assertEqual(UserInstituteMembership.objects.count(), membership_count_before)

        detail = self.client.get(reverse('institute-detail', kwargs={'institute_id': response.data['id']}))
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data['code'], 'GAMMA')
        overview = self.client.get(reverse('platform-dashboard-overview'))
        self.assertEqual(overview.status_code, status.HTTP_200_OK)
        self.assertEqual(overview.data['total_institutes'], 3)
        self.assertEqual(overview.data['active_institutes'], 3)

    def test_institute_admin_cannot_create_institute(self):
        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('institute-list-create')
        response = self.client.post(url, {
            'code': 'DELTA',
            'name': 'Delta Institute'
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_platform_admin_can_provision_first_institute_admin(self):
        self.client.force_authenticate(user=self.platform_admin)
        url = reverse('institute-provision-admin', kwargs={'institute_id': self.institute_alpha.id})
        response = self.client.post(url, {
            'email': 'newlead@alpha.edu',
            'first_name': 'New',
            'last_name': 'Lead',
            'temporary_password': 'TempAdminPassword123!'
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='newlead@alpha.edu').exists())
        membership = UserInstituteMembership.objects.get(
            user__email='newlead@alpha.edu',
            institute=self.institute_alpha
        )
        self.assertEqual(membership.role, RoleChoices.INSTITUTE_ADMIN)

    def test_cross_institute_access_is_forbidden(self):
        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('institute-members-list-create', kwargs={'institute_id': self.institute_beta.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_institute_admin_can_manage_own_members(self):
        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('institute-members-list-create', kwargs={'institute_id': self.institute_alpha.id})

        # Create teacher
        response = self.client.post(url, {
            'email': 'newteacher@alpha.edu',
            'first_name': 'Margaret',
            'last_name': 'Hamilton',
            'role': RoleChoices.TEACHER,
            'identifier': 'FAC099',
            'initial_password': 'MargaretInitial!45',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['role'], RoleChoices.TEACHER)

        # List members
        list_resp = self.client.get(url)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(any('newteacher@alpha.edu' in str(m) for m in list_resp.data))

    def test_teacher_and_student_members_use_admin_set_password_and_log_in(self):
        self.client.force_authenticate(user=self.alpha_admin)
        members_url = reverse(
            'institute-members-list-create',
            kwargs={'institute_id': self.institute_alpha.id},
        )

        teacher_response = self.client.post(members_url, {
            'email': 'activated.teacher@alpha.edu',
            'first_name': 'Activated',
            'last_name': 'Teacher',
            'role': RoleChoices.TEACHER,
            'identifier': 'FAC100',
            'initial_password': 'TeacherInitial!45',
        })
        self.assertEqual(teacher_response.status_code, status.HTTP_201_CREATED)
        teacher_user = User.objects.get(email='activated.teacher@alpha.edu')
        self.assertTrue(teacher_user.is_active)
        self.assertTrue(teacher_user.is_verified)
        self.assertTrue(teacher_user.must_change_password)
        self.assertTrue(teacher_user.check_password('TeacherInitial!45'))
        self.assertTrue(teacher_response.data['initial_password_set'])
        self.assertNotIn('initial_password', teacher_response.data)
        self.assertNotIn('TeacherInitial!45', str(teacher_response.data))
        self.assertEqual(len(mail.outbox), 0)
        teacher_login = self.client.post(reverse('auth-login'), {
            'email': 'activated.teacher@alpha.edu',
            'password': 'TeacherInitial!45',
        })
        self.assertEqual(teacher_login.status_code, status.HTTP_200_OK)
        self.assertTrue(teacher_login.data['must_change_password'])
        self.assertEqual(
            teacher_login.data['user']['memberships'][0]['role'],
            RoleChoices.TEACHER,
        )
        self.assertEqual(
            UserInstituteMembership.objects.get(user__email='activated.teacher@alpha.edu').status,
            MembershipStatus.ACTIVE,
        )

        student_response = self.client.post(members_url, {
            'email': 'activated.student@alpha.edu',
            'first_name': 'Activated',
            'last_name': 'Student',
            'role': RoleChoices.STUDENT,
            'identifier': 'ROLL100',
            'department': str(self.department_alpha.id),
            'batch': str(self.batch_alpha.id),
            'subject_ids': [str(self.subject_alpha.id)],
            'initial_password': 'StudentInitial!45',
        })
        self.assertEqual(student_response.status_code, status.HTTP_201_CREATED)
        student_membership = UserInstituteMembership.objects.get(
            user__email='activated.student@alpha.edu',
            institute=self.institute_alpha,
        )
        self.assertEqual(student_membership.subject_enrollments.filter(status='active').count(), 1)
        student_user = User.objects.get(email='activated.student@alpha.edu')
        self.assertTrue(student_user.is_active)
        self.assertTrue(student_user.is_verified)
        self.assertTrue(student_user.must_change_password)
        self.assertTrue(student_user.check_password('StudentInitial!45'))
        self.assertEqual(len(mail.outbox), 0)
        student_login = self.client.post(reverse('auth-login'), {
            'email': 'activated.student@alpha.edu',
            'password': 'StudentInitial!45',
        })
        self.assertEqual(student_login.status_code, status.HTTP_200_OK)
        self.assertTrue(student_login.data['must_change_password'])
        self.assertEqual(
            student_login.data['user']['memberships'][0]['role'],
            RoleChoices.STUDENT,
        )
        student_membership.refresh_from_db()
        self.assertEqual(student_membership.status, MembershipStatus.ACTIVE)

    def test_member_creation_works_without_smtp_and_requires_strong_initial_password(self):
        self.client.force_authenticate(user=self.alpha_admin)
        with override_settings(EMAIL_HOST='', DEFAULT_FROM_EMAIL=''):
            response = self.client.post(
                reverse(
                    'institute-members-list-create',
                    kwargs={'institute_id': self.institute_alpha.id},
                ),
                {
                    'email': 'no.activation@alpha.edu',
                    'first_name': 'No',
                    'last_name': 'Activation',
                    'role': RoleChoices.TEACHER,
                    'initial_password': 'SecureInitial!58',
                },
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        account = User.objects.get(email='no.activation@alpha.edu')
        self.assertTrue(account.check_password('SecureInitial!58'))
        self.assertEqual(response.data['initial_password_set'], True)
        self.assertEqual(len(mail.outbox), 0)

        weak_response = self.client.post(
            reverse(
                'institute-members-list-create',
                kwargs={'institute_id': self.institute_alpha.id},
            ),
            {
                'email': 'weak.password@alpha.edu',
                'first_name': 'Weak',
                'last_name': 'Password',
                'role': RoleChoices.TEACHER,
                'initial_password': '12345678',
            },
        )
        self.assertEqual(weak_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email='weak.password@alpha.edu').exists())

    def test_adding_existing_account_does_not_overwrite_its_password(self):
        existing = User.objects.create_user(
            email='existing@beta.edu',
            password='ExistingAccount!45',
            is_active=True,
            is_verified=True,
        )
        UserInstituteMembership.objects.create(
            user=existing,
            institute=self.institute_beta,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE,
        )
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.post(
            reverse(
                'institute-members-list-create',
                kwargs={'institute_id': self.institute_alpha.id},
            ),
            {
                'email': existing.email,
                'first_name': 'Existing',
                'last_name': 'Account',
                'role': RoleChoices.TEACHER,
                'initial_password': 'NotReplacing!45',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertFalse(response.data['initial_password_set'])
        existing.refresh_from_db()
        self.assertTrue(existing.check_password('ExistingAccount!45'))
        self.assertFalse(existing.check_password('NotReplacing!45'))

    def test_membership_patch_cannot_change_user_or_institute(self):
        membership = UserInstituteMembership.objects.get(
            user=self.student_alpha,
            institute=self.institute_alpha,
        )
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.patch(
            reverse('institute-member-detail', kwargs={
                'institute_id': self.institute_alpha.id,
                'membership_id': membership.id,
            }),
            {
                'user': str(self.teacher_alpha.id),
                'institute': str(self.institute_beta.id),
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        membership.refresh_from_db()
        self.assertEqual(membership.user_id, self.student_alpha.id)
        self.assertEqual(membership.institute_id, self.institute_alpha.id)

    def test_privilege_escalation_blocked(self):
        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('institute-members-list-create', kwargs={'institute_id': self.institute_alpha.id})
        response = self.client.post(url, {
            'email': 'hacker@alpha.edu',
            'first_name': 'Bad',
            'last_name': 'Actor',
            'role': 'platform_admin'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_teacher_cannot_add_members(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('institute-members-list-create', kwargs={'institute_id': self.institute_alpha.id})
        response = self.client.post(url, {
            'email': 'student2@alpha.edu',
            'first_name': 'Jane',
            'last_name': 'Doe',
            'role': RoleChoices.STUDENT
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_deactivate_member_workflow(self):
        membership = UserInstituteMembership.objects.get(
            user=self.student_alpha,
            institute=self.institute_alpha
        )
        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('institute-member-deactivate', kwargs={
            'institute_id': self.institute_alpha.id,
            'membership_id': membership.id
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        membership.refresh_from_db()
        self.assertEqual(membership.status, MembershipStatus.INACTIVE)

    # --------------------------------------------------------------------------
    # Bulk CSV and Excel Import Workflow Tests
    # --------------------------------------------------------------------------

    def test_bulk_csv_import_validation_and_confirmation(self):
        csv_content = (
            "email,first_name,last_name,identifier,department_code,batch_name,subject_codes\n"
            "student_valid_1@alpha.edu,John,Doe,S101,CSE,CSE 2026,CS101\n"
            "student_valid_2@alpha.edu,Jane,Smith,S102,CSE,CSE 2026,CS101\n"
            "invalid-email-row,Bad,Email,S103,CSE,CSE 2026,CS101\n"
            "student@alpha.edu,Existing,Student,ROLL001,CSE,CSE 2026,CS101\n"
            "student_valid_1@alpha.edu,Duplicate,InFile,S105,CSE,CSE 2026,CS101\n"
        )
        csv_file = io.BytesIO(csv_content.encode('utf-8'))
        csv_file.name = 'students_batch.csv'

        self.client.force_authenticate(user=self.alpha_admin)
        upload_url = reverse('institute-import-upload', kwargs={'institute_id': self.institute_alpha.id})

        # 1. Upload file
        response = self.client.post(
            upload_url,
            {'file': csv_file, 'import_type': 'students'},
            format='multipart'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        job_id = response.data['id']
        self.assertEqual(response.data['status'], ImportStatus.VALIDATED)
        self.assertEqual(response.data['total_rows'], 5)
        self.assertEqual(response.data['valid_rows'], 2)
        self.assertEqual(response.data['error_rows'], 3)

        # 2. Preview endpoint
        preview_url = reverse('institute-import-preview', kwargs={
            'institute_id': self.institute_alpha.id,
            'job_id': job_id
        })
        prev_resp = self.client.get(preview_url)
        self.assertEqual(prev_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(prev_resp.data['valid_candidates_preview']), 2)
        self.assertEqual(len(prev_resp.data['errors']), 4)

        # 3. Confirm import
        confirm_url = reverse('institute-import-confirm', kwargs={
            'institute_id': self.institute_alpha.id,
            'job_id': job_id
        })
        confirm_resp = self.client.post(confirm_url)
        self.assertEqual(confirm_resp.status_code, status.HTTP_200_OK)

        self.assertTrue(User.objects.filter(email='student_valid_1@alpha.edu').exists())
        self.assertTrue(User.objects.filter(email='student_valid_2@alpha.edu').exists())

        u1 = User.objects.get(email='student_valid_1@alpha.edu')
        self.assertTrue(u1.must_change_password)
        m1 = UserInstituteMembership.objects.get(user=u1, institute=self.institute_alpha)
        self.assertEqual(m1.role, RoleChoices.STUDENT)
        self.assertEqual(m1.identifier, 'S101')
        self.assertEqual(m1.academic_placements.filter(status='active').count(), 1)
        self.assertEqual(m1.subject_enrollments.filter(status='active').count(), 1)

    def test_bulk_import_detects_duplicates_even_when_first_row_has_other_errors(self):
        csv_content = (
            'email,first_name,last_name,roll_number,department_code,batch_name,subject_codes\n'
            ',,First Invalid,DUP100,CSE,CSE 2026,CS101\n'
            'repeat@alpha.edu,Second,Row,DUP200,CSE,CSE 2026,CS101\n'
            'repeat@alpha.edu,Third,Row,DUP300,CSE,CSE 2026,CS101\n'
            'unique@alpha.edu,Fourth,Row,DUP100,CSE,CSE 2026,CS101\n'
        )
        csv_file = io.BytesIO(csv_content.encode('utf-8'))
        csv_file.name = 'duplicate_students.csv'
        self.client.force_authenticate(user=self.alpha_admin)
        response = self.client.post(
            reverse('institute-import-upload', kwargs={'institute_id': self.institute_alpha.id}),
            {'file': csv_file, 'import_type': 'students'},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['valid_rows'], 1)
        self.assertEqual(response.data['error_rows'], 3)

        errors = response.data['row_errors']
        codes = {(error['row_number'], error['error_code']) for error in errors}
        self.assertIn((4, 'duplicate_in_file'), codes)
        self.assertIn((5, 'duplicate_identifier_in_file'), codes)

    def test_malformed_xlsx_is_reported_as_a_file_error(self):
        invalid_file = io.BytesIO(b'not an xlsx archive')
        invalid_file.name = 'students.xlsx'
        self.client.force_authenticate(user=self.alpha_admin)

        response = self.client.post(
            reverse('institute-import-upload', kwargs={'institute_id': self.institute_alpha.id}),
            {'file': invalid_file, 'import_type': 'students'},
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], ImportStatus.FAILED)
        self.assertEqual(response.data['error_rows'], 1)
        self.assertEqual(response.data['row_errors'][0]['error_code'], 'invalid_file')

    def test_bulk_excel_import_validation(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['email', 'first_name', 'last_name', 'identifier'])
        ws.append(['faculty_1@alpha.edu', 'Charles', 'Babbage', 'FAC301'])
        ws.append(['faculty_2@alpha.edu', 'Katherine', 'Johnson', 'FAC302'])

        excel_io = io.BytesIO()
        wb.save(excel_io)
        excel_io.seek(0)
        excel_io.name = 'faculty_import.xlsx'

        self.client.force_authenticate(user=self.alpha_admin)
        upload_url = reverse('institute-import-upload', kwargs={'institute_id': self.institute_alpha.id})

        response = self.client.post(
            upload_url,
            {'file': excel_io, 'import_type': 'teachers'},
            format='multipart'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], ImportStatus.VALIDATED)
        self.assertEqual(response.data['valid_rows'], 2)
        self.assertEqual(response.data['error_rows'], 0)
