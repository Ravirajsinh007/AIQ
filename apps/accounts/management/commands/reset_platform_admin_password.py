from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q

from apps.accounts.models import MembershipStatus, RoleChoices, User
from apps.audit.services import record_audit_event


class Command(BaseCommand):
    help = 'Reset the password for the existing sole Platform Admin on PostgreSQL.'

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError('Refusing to reset a Platform Admin password unless PostgreSQL is active.')

        email = input('Existing Platform Admin email: ').strip().lower()
        new_password = getpass('New Platform Admin password (input hidden): ')
        confirmation = getpass('Confirm new Platform Admin password (input hidden): ')
        if not new_password or new_password != confirmation:
            raise CommandError('The passwords were empty or did not match; no changes were made.')

        with transaction.atomic():
            self._lock_provisioning()
            administrators = self._platform_admins()
            user = User.objects.select_for_update().filter(email__iexact=email).first()

            if not user or not user.is_active or not user.is_platform_admin:
                raise CommandError('No active Platform Admin matches that email; no changes were made.')
            if administrators.count() != 1 or not administrators.filter(pk=user.pk).exists():
                raise CommandError('The database does not have exactly one matching Platform Admin.')
            if input('Type RESET to replace this account password: ').strip() != 'RESET':
                raise CommandError('Password reset was not confirmed; no changes were made.')

            try:
                validate_password(new_password, user=user)
            except ValidationError as exc:
                raise CommandError('; '.join(exc.messages)) from exc

            user.set_password(new_password)
            user.must_change_password = False
            user.save(update_fields=['password', 'must_change_password', 'updated_at'])
            record_audit_event(
                action='account.platform_admin_password_reset',
                resource_type='accounts.user',
                resource_id=user.pk,
            )

        self.stdout.write(self.style.SUCCESS('Existing Platform Admin password reset successfully.'))

    @staticmethod
    def _lock_provisioning():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [73169420261023])

    @staticmethod
    def _platform_admins():
        return User.objects.filter(
            Q(is_superuser=True)
            | Q(
                memberships__role=RoleChoices.PLATFORM_ADMIN,
                memberships__status=MembershipStatus.ACTIVE,
            )
        ).distinct()
