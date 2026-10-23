from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.accounts.management.commands.provision_examcraft_test_accounts import TEST_ACCOUNTS
from apps.accounts.models import Institute, User, UserInstituteMembership
from apps.academics.models import StudentAcademicPlacement, TeacherAssignment


@override_settings(DEBUG=True)
class DevelopmentTestAccountProvisioningTests(TestCase):
    def test_provisioning_is_idempotent_and_hashes_passwords(self):
        call_command('provision_examcraft_test_accounts', stdout=StringIO())
        first_user_ids = set(User.objects.values_list('id', flat=True))
        first_membership_ids = set(UserInstituteMembership.objects.values_list('id', flat=True))

        call_command('provision_examcraft_test_accounts', stdout=StringIO())

        self.assertEqual(User.objects.count(), 4)
        self.assertEqual(UserInstituteMembership.objects.count(), 4)
        self.assertEqual(set(User.objects.values_list('id', flat=True)), first_user_ids)
        self.assertEqual(
            set(UserInstituteMembership.objects.values_list('id', flat=True)),
            first_membership_ids,
        )
        for account in TEST_ACCOUNTS:
            user = User.objects.get(email=account['email'])
            self.assertTrue(user.check_password(account['password']))
            self.assertNotEqual(user.password, account['password'])
            self.assertEqual(user.memberships.get().role, account['role'])

        institute = Institute.objects.get(code='EXAMCRAFT-LOCAL')
        teacher = User.objects.get(email='teacher@examcraft.local')
        student = User.objects.get(email='student@examcraft.local')
        self.assertEqual(
            TeacherAssignment.objects.filter(teacher__user=teacher).count(),
            1,
        )
        self.assertEqual(
            StudentAcademicPlacement.objects.filter(student__user=student).count(),
            1,
        )
        self.assertEqual(institute.memberships.count(), 4)

    def test_existing_test_user_password_is_not_reset(self):
        institute = Institute.objects.create(
            code='EXAMCRAFT-LOCAL',
            name='ExamCraft Local Development Institute',
        )
        user = User.objects.create_user(
            email='student@examcraft.local',
            password='A_Preexisting_Password_2026!',
        )
        UserInstituteMembership.objects.create(
            user=user,
            institute=institute,
            role='student',
            status='active',
        )

        call_command('provision_examcraft_test_accounts', stdout=StringIO())

        user.refresh_from_db()
        self.assertTrue(user.check_password('A_Preexisting_Password_2026!'))
        self.assertFalse(user.check_password('EC_Student_2026!'))
