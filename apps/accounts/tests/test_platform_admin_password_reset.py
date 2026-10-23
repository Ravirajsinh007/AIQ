from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase

from apps.accounts.models import Institute, User, UserInstituteMembership
from apps.audit.models import AuditEvent


class PlatformAdminPasswordResetTests(TestCase):
    def run_reset(self, email, password, password_confirmation=None, approval='RESET'):
        if password_confirmation is None:
            password_confirmation = password
        with (
            patch('apps.accounts.management.commands.reset_platform_admin_password.connection.vendor', 'postgresql'),
            patch(
                'apps.accounts.management.commands.reset_platform_admin_password.Command._lock_provisioning',
                return_value=None,
            ),
            patch('builtins.input', side_effect=[email, approval]),
            patch(
                'apps.accounts.management.commands.reset_platform_admin_password.getpass',
                side_effect=[password, password_confirmation],
            ),
        ):
            output = StringIO()
            call_command('reset_platform_admin_password', stdout=output)
        return output.getvalue()

    def test_refuses_non_postgresql(self):
        with patch(
            'apps.accounts.management.commands.reset_platform_admin_password.connection.vendor',
            connection.vendor,
        ), patch('builtins.input') as prompt:
            with self.assertRaisesMessage(CommandError, 'unless PostgreSQL is active'):
                call_command('reset_platform_admin_password', stdout=StringIO())
        prompt.assert_not_called()

    def test_resets_only_existing_sole_admin_with_explicit_confirmation(self):
        admin = User.objects.create_superuser(
            email='platform.admin@example.test',
            password='Old-Platform-Password-92!A',
        )
        new_password = '7R!mosaic_Cirrus-9421'

        output = self.run_reset(admin.email, new_password)

        admin.refresh_from_db()
        self.assertTrue(admin.check_password(new_password))
        self.assertFalse(admin.check_password('Old-Platform-Password-92!A'))
        self.assertTrue(admin.is_platform_admin)
        self.assertFalse(admin.must_change_password)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Institute.objects.count(), 0)
        self.assertEqual(UserInstituteMembership.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.filter(action='account.platform_admin_password_reset').count(), 1)
        self.assertNotIn(new_password, output)

    def test_rejects_reset_without_confirmation(self):
        admin = User.objects.create_superuser(
            email='platform.admin@example.test',
            password='Old-Platform-Password-92!A',
        )

        with self.assertRaisesMessage(CommandError, 'Password reset was not confirmed'):
            self.run_reset(admin.email, '7R!mosaic_Cirrus-9421', approval='no')

        admin.refresh_from_db()
        self.assertTrue(admin.check_password('Old-Platform-Password-92!A'))
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_rejects_mismatched_password_confirmation(self):
        admin = User.objects.create_superuser(
            email='platform.admin@example.test',
            password='Old-Platform-Password-92!A',
        )

        with self.assertRaisesMessage(CommandError, 'did not match'):
            self.run_reset(admin.email, '7R!mosaic_Cirrus-9421', '7R!mosaic_Cirrus-9422')

        admin.refresh_from_db()
        self.assertTrue(admin.check_password('Old-Platform-Password-92!A'))
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_rejects_wrong_email_and_duplicate_admins(self):
        admin = User.objects.create_superuser(
            email='platform.admin@example.test',
            password='Old-Platform-Password-92!A',
        )
        with self.assertRaisesMessage(CommandError, 'No active Platform Admin matches'):
            self.run_reset('wrong@example.test', '7R!mosaic_Cirrus-9421')

        User.objects.create_superuser(
            email='second.admin@example.test',
            password='Old-Platform-Password-92!A',
        )
        with self.assertRaisesMessage(CommandError, 'does not have exactly one'):
            self.run_reset(admin.email, '7R!mosaic_Cirrus-9421')

        admin.refresh_from_db()
        self.assertTrue(admin.check_password('Old-Platform-Password-92!A'))
        self.assertEqual(AuditEvent.objects.count(), 0)
