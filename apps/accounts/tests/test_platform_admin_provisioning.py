from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import TestCase
from django.db import connection

from apps.accounts.models import Institute, RoleChoices, User, UserInstituteMembership


class PlatformAdminProvisioningTests(TestCase):
    def run_command(self, email, password):
        with (
            patch('apps.accounts.management.commands.provision_platform_admin.connection.vendor', 'postgresql'),
            patch(
                'apps.accounts.management.commands.provision_platform_admin.Command._lock_provisioning',
                return_value=None,
            ),
            patch('builtins.input', return_value=email),
            patch(
                'apps.accounts.management.commands.provision_platform_admin.getpass',
                side_effect=[password, password],
            ),
        ):
            output = StringIO()
            call_command('provision_platform_admin', stdout=output)
        return output.getvalue()

    def test_refuses_non_postgresql_without_prompting(self):
        with patch(
            'apps.accounts.management.commands.provision_platform_admin.connection.vendor',
            connection.vendor,
        ), patch('builtins.input') as prompt:
            with self.assertRaisesMessage(CommandError, 'unless PostgreSQL is active'):
                call_command('provision_platform_admin', stdout=StringIO())
        prompt.assert_not_called()
        self.assertEqual(User.objects.count(), 0)

    def test_creates_one_superuser_without_institute_and_is_repeatable(self):
        email = 'platform.admin@example.test'
        password = 'Secure-Platform-Password-92!A'

        first_output = self.run_command(email, password)
        second_output = self.run_command(email, password)

        admin = User.objects.get(email=email)
        self.assertTrue(admin.check_password(password))
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_platform_admin)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Institute.objects.count(), 0)
        self.assertEqual(UserInstituteMembership.objects.count(), 0)
        self.assertIn('account created', first_output)
        self.assertIn('verified', second_output)
        self.assertNotIn(password, first_output + second_output)

    def test_reuses_existing_platform_admin_without_changing_password(self):
        password = 'Existing-Platform-Password-92!A'
        admin = User.objects.create_superuser(
            email='platform.admin@example.test',
            password=password,
        )

        self.run_command(admin.email, password)

        admin.refresh_from_db()
        self.assertTrue(admin.check_password(password))
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Institute.objects.count(), 0)

    def test_refuses_to_create_a_second_platform_admin(self):
        User.objects.create_superuser(
            email='existing.admin@example.test',
            password='Existing-Platform-Password-92!A',
        )

        with self.assertRaisesMessage(CommandError, 'A different Platform Admin already exists'):
            self.run_command('another.admin@example.test', 'Another-Platform-Password-92!A')

        self.assertEqual(User.objects.count(), 1)
