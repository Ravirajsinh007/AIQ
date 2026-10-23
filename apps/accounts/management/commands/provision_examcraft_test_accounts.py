from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.accounts.models import (
    Institute,
    MembershipStatus,
    RoleChoices,
    User,
    UserInstituteMembership,
)
from apps.academics.models import (
    AcademicYear,
    Batch,
    Department,
    Program,
    ProgramSemesterSubject,
    Section,
    Semester,
    StudentAcademicPlacement,
    Subject,
    TeacherAssignment,
)


TEST_ACCOUNTS = (
    {
        'email': 'platform.admin@examcraft.local',
        'password': 'EC_Platform_2026!',
        'first_name': 'Platform',
        'last_name': 'Administrator',
        'role': RoleChoices.PLATFORM_ADMIN,
        'identifier': '',
    },
    {
        'email': 'institute.admin@examcraft.local',
        'password': 'EC_Institute_2026!',
        'first_name': 'Institute',
        'last_name': 'Administrator',
        'role': RoleChoices.INSTITUTE_ADMIN,
        'identifier': '',
    },
    {
        'email': 'teacher@examcraft.local',
        'password': 'EC_Teacher_2026!',
        'first_name': 'ExamCraft',
        'last_name': 'Teacher',
        'role': RoleChoices.TEACHER,
        'identifier': 'EC-TEACHER-001',
    },
    {
        'email': 'student@examcraft.local',
        'password': 'EC_Student_2026!',
        'first_name': 'ExamCraft',
        'last_name': 'Student',
        'role': RoleChoices.STUDENT,
        'identifier': 'EC-STUDENT-001',
    },
)

INSTITUTE_CODE = 'EXAMCRAFT-LOCAL'
INSTITUTE_NAME = 'ExamCraft Local Development Institute'


class Command(BaseCommand):
    help = 'Provision four local-only ExamCraft role accounts and academic relationships.'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Refusing to provision test accounts unless DJANGO_DEBUG is enabled.')
        if connection.vendor != 'sqlite':
            raise CommandError('Refusing to provision test accounts on a non-SQLite database.')

        with transaction.atomic():
            institute, _ = Institute.objects.get_or_create(
                code=INSTITUTE_CODE,
                defaults={'name': INSTITUTE_NAME, 'status': 'active'},
            )
            if institute.name != INSTITUTE_NAME:
                raise CommandError(
                    f'Institute code {INSTITUTE_CODE} already belongs to a different institute.'
                )

            department, _ = Department.objects.get_or_create(
                institute=institute,
                code='EC-LOCAL-CS',
                defaults={'name': 'Computer Science'},
            )
            program, _ = Program.objects.get_or_create(
                institute=institute,
                code='EC-LOCAL-MCA',
                defaults={
                    'department': department,
                    'name': 'MCA Development Program',
                    'qualification_type': 'postgraduate',
                    'duration_years': 2,
                    'total_semesters': 4,
                },
            )
            academic_year, _ = AcademicYear.objects.get_or_create(
                institute=institute,
                label='2026-2027',
                defaults={
                    'start_date': date(2026, 6, 1),
                    'end_date': date(2027, 5, 31),
                    'is_current': True,
                },
            )
            semester, _ = Semester.objects.get_or_create(
                program=program,
                semester_number=1,
                defaults={'label': 'Semester 1'},
            )
            batch, _ = Batch.objects.get_or_create(
                program=program,
                name='2026 Development Cohort',
                defaults={
                    'institute': institute,
                    'admission_year': 2026,
                },
            )
            section, _ = Section.objects.get_or_create(
                batch=batch,
                name='A',
            )
            subject, _ = Subject.objects.get_or_create(
                institute=institute,
                code='EC-FOUNDATIONS',
                defaults={
                    'department': department,
                    'name': 'Assessment Design Foundations',
                    'description': 'Development course for verifying ExamCraft workflows.',
                },
            )
            ProgramSemesterSubject.objects.get_or_create(
                program=program,
                semester=semester,
                subject=subject,
            )

            memberships = {}
            for account in TEST_ACCOUNTS:
                user = self._get_or_create_user(account)
                membership = self._get_or_create_membership(user, institute, account)
                memberships[account['role']] = membership

            TeacherAssignment.objects.get_or_create(
                teacher=memberships[RoleChoices.TEACHER],
                subject=subject,
                academic_year=academic_year,
                defaults={'batch': batch, 'section': section},
            )
            StudentAcademicPlacement.objects.get_or_create(
                student=memberships[RoleChoices.STUDENT],
                program=program,
                batch=batch,
                semester=semester,
                defaults={'section': section},
            )

        self.stdout.write(self.style.SUCCESS(
            'Provisioned or verified 4 local test accounts, one development institute, '
            'and the teacher/student course relationships. Existing passwords were preserved.'
        ))
        for account in TEST_ACCOUNTS:
            self.stdout.write(f"{account['role']}: {account['email']}")

    def _get_or_create_user(self, account):
        user = User.objects.filter(email=account['email']).first()
        if user is None:
            return User.objects.create_user(
                email=account['email'],
                password=account['password'],
                first_name=account['first_name'],
                last_name=account['last_name'],
                is_active=True,
                is_verified=True,
                must_change_password=False,
            )
        if not user.is_active:
            raise CommandError(
                f"{account['email']} already exists but is inactive; it was not modified."
            )
        return user

    def _get_or_create_membership(self, user, institute, account):
        existing = list(UserInstituteMembership.objects.filter(user=user))
        conflicting = [membership for membership in existing if membership.role != account['role']]
        if conflicting:
            roles = ', '.join(sorted({membership.role for membership in conflicting}))
            raise CommandError(
                f"{account['email']} has conflicting role membership(s): {roles}; no role was changed."
            )

        membership, created = UserInstituteMembership.objects.get_or_create(
            user=user,
            institute=institute,
            defaults={
                'role': account['role'],
                'identifier': account['identifier'],
                'status': MembershipStatus.ACTIVE,
                'is_verified': True,
            },
        )
        if membership.role != account['role'] or membership.status != MembershipStatus.ACTIVE:
            raise CommandError(
                f"{account['email']} has a non-active or conflicting development membership; "
                'it was not modified.'
            )
        if created:
            return membership

        if account['identifier'] and not membership.identifier:
            membership.identifier = account['identifier']
            membership.save(update_fields=['identifier', 'updated_at'])
        return membership
