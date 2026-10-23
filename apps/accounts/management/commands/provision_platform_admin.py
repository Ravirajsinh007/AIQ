from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q

from apps.accounts.models import MembershipStatus, RoleChoices, User


class Command(BaseCommand):
    help = 'Safely create or verify one Platform Admin on the configured PostgreSQL database.'

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError('Refusing to provision a Platform Admin unless PostgreSQL is active.')

        email = input('Platform Admin email: ').strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError('Enter a valid email address.') from exc

        password = getpass('Platform Admin password (input hidden): ')
        confirmation = getpass('Confirm Platform Admin password (input hidden): ')
        if not password or password != confirmation:
            raise CommandError('The passwords were empty or did not match; no changes were made.')

        with transaction.atomic():
            self._lock_provisioning()
            admins = self._platform_admins()
            user = User.objects.select_for_update().filter(email__iexact=email).first()

            if user and not user.is_active:
                raise CommandError('The matching account is inactive; no changes were made.')
            if user and not user.check_password(password):
                raise CommandError('The supplied password did not authenticate the matching account.')
            if user and admins.exclude(pk=user.pk).exists():
                raise CommandError(
                    'A different Platform Admin already exists; no additional account was created.'
                )
            if not user and admins.exists():
                raise CommandError(
                    'A different Platform Admin already exists; no additional account was created.'
                )

            if user:
                if not user.is_platform_admin:
                    try:
                        validate_password(password, user=user)
                    except ValidationError as exc:
                        raise CommandError('; '.join(exc.messages)) from exc
                    user.is_staff = True
                    user.is_superuser = True
                    user.save(update_fields=['is_staff', 'is_superuser', 'updated_at'])
                message = 'Existing Platform Admin verified.'
            else:
                try:
                    validate_password(password)
                except ValidationError as exc:
                    raise CommandError('; '.join(exc.messages)) from exc
                User.objects.create_superuser(
                    email=email,
                    password=password,
                    is_verified=True,
                    must_change_password=False,
                )
                message = 'Platform Admin account created.'

            if self._platform_admins().count() != 1:
                raise CommandError(
                    'The database does not contain exactly one Platform Admin; transaction rolled back.'
                )

        self.stdout.write(self.style.SUCCESS(message))

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
