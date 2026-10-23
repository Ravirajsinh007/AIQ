import csv
import io
import re
import smtplib
import zipfile
from typing import Tuple, List, Dict, Any
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from openpyxl.utils.exceptions import InvalidFileException
from rest_framework.exceptions import APIException
from .models import (
    User,
    Institute,
    UserInstituteMembership,
    RoleChoices,
    MembershipStatus,
    AccountVerification,
    BulkImportJob,
    BulkImportRowError,
    ImportStatus,
    ImportType,
)

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')


class ActivationDeliveryError(APIException):
    status_code = 503
    default_detail = 'Account activation email could not be delivered. Configure SMTP and retry.'
    default_code = 'activation_email_unavailable'


def send_activation_email(user: User) -> None:
    if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:
        raise ActivationDeliveryError()

    AccountVerification.objects.filter(
        user=user,
        purpose=AccountVerification.PURPOSE_ACTIVATION,
        used_at__isnull=True,
    ).update(used_at=timezone.now())
    _, code = AccountVerification.create_verification(
        user=user,
        purpose=AccountVerification.PURPOSE_ACTIVATION,
    )
    activation_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/activate-account"
    message = (
        f"Hello {user.first_name or user.email},\n\n"
        "Your ExamCraft account is ready. Activate it by setting your own password.\n\n"
        f"Activation code: {code}\n"
        f"Open: {activation_url}\n\n"
        "This code expires in 60 minutes and can be used only once."
    )
    try:
        sent_count = send_mail(
            subject='Activate your ExamCraft account',
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except (OSError, smtplib.SMTPException) as exc:
        raise ActivationDeliveryError() from exc
    if sent_count != 1:
        raise ActivationDeliveryError()


class BulkImportService:
    """
    Handles CSV and XLSX bulk parsing, row-level validation, duplicate detection,
    and database commit upon confirmation.
    """

    @staticmethod
    def parse_and_validate(import_job: BulkImportJob, file_obj) -> BulkImportJob:
        filename = import_job.file_name.lower()
        rows: List[Dict[str, Any]] = []

        try:
            if filename.endswith('.csv'):
                rows = BulkImportService._read_csv(file_obj)
            elif filename.endswith('.xlsx'):
                rows = BulkImportService._read_xlsx(file_obj)
            else:
                BulkImportService._record_file_error(
                    import_job,
                    'unsupported_format',
                    'Unsupported file format. Please upload a .csv or .xlsx file.',
                )
                return import_job
        except (InvalidFileException, zipfile.BadZipFile, OSError, csv.Error, UnicodeError):
            BulkImportService._record_file_error(
                import_job,
                'invalid_file',
                'The uploaded file could not be read as a valid CSV or XLSX roster.',
            )
            return import_job

        if not rows:
            BulkImportService._record_file_error(
                import_job,
                'empty_file',
                'The roster has no student or teacher rows.',
            )
            return import_job

        import_job.total_rows = len(rows)
        valid_records: List[Dict[str, Any]] = []
        seen_emails_in_file = set()
        seen_identifiers_in_file = set()

        # Existing members for this institute
        existing_emails = set(
            email.casefold()
            for email in UserInstituteMembership.objects.filter(
                institute=import_job.institute
            ).values_list('user__email', flat=True)
        )
        existing_identifiers = {
            identifier.casefold()
            for identifier in UserInstituteMembership.objects.filter(
                institute=import_job.institute
            ).exclude(identifier='').values_list('identifier', flat=True)
        }

        role = RoleChoices.STUDENT if import_job.import_type == ImportType.STUDENTS else RoleChoices.TEACHER

        for idx, row in enumerate(rows, start=2):  # Row 1 is header
            errors = []
            email = str(row.get('email', '')).strip().lower()
            first_name = str(row.get('first_name', '')).strip()
            last_name = str(row.get('last_name', '')).strip()
            identifier = str(row.get('identifier', row.get('roll_number', row.get('employee_id', '')))).strip()
            if role == RoleChoices.STUDENT:
                identifier = identifier.upper()
            phone_number = str(row.get('phone_number', '')).strip()

            # 1. Email validation
            if not email:
                errors.append(('email', 'missing_email', 'Email address is required.'))
            elif not EMAIL_REGEX.match(email):
                errors.append(('email', 'invalid_email', f"Invalid email format: '{email}'"))
            elif email.casefold() in seen_emails_in_file:
                errors.append(('email', 'duplicate_in_file', f"Duplicate email in upload: '{email}'"))
            elif email.casefold() in existing_emails:
                errors.append(('email', 'duplicate_in_institute', f"User with email '{email}' is already a member of this institute."))
            elif EMAIL_REGEX.match(email):
                seen_emails_in_file.add(email.casefold())

            academic_row = None
            if role == RoleChoices.STUDENT:
                from apps.academics.models import AcademicStatus, Batch, Department, Subject

                department_code = str(row.get('department_code', row.get('department', ''))).strip()
                batch_name = str(row.get('batch_name', row.get('batch', ''))).strip()
                raw_subject_codes = str(row.get('subject_codes', row.get('subjects', ''))).strip()
                subject_codes = [
                    code.strip() for code in re.split(r'[,;|]', raw_subject_codes) if code.strip()
                ]
                department = Department.objects.filter(
                    institute=import_job.institute,
                    code__iexact=department_code,
                    status=AcademicStatus.ACTIVE,
                ).first() if department_code else None
                if department is None:
                    errors.append(('department_code', 'invalid_department', 'Select an active department by code.'))

                batch = Batch.objects.select_related('program').filter(
                    institute=import_job.institute,
                    name__iexact=batch_name,
                    status=AcademicStatus.ACTIVE,
                    program__department=department,
                ).first() if department and batch_name else None
                if batch is None:
                    errors.append(('batch_name', 'invalid_batch', 'Select an active batch name within the selected department.'))

                if not subject_codes:
                    errors.append(('subject_codes', 'missing_subjects', 'At least one subject code is required.'))
                elif len({code.casefold() for code in subject_codes}) != len(subject_codes):
                    errors.append(('subject_codes', 'duplicate_subject', 'A subject code may only be listed once.'))

                available_subjects = {
                    subject.code.casefold(): subject
                    for subject in Subject.objects.filter(
                        institute=import_job.institute,
                        department=department,
                        status=AcademicStatus.ACTIVE,
                    )
                } if department else {}
                subjects = [available_subjects[code.casefold()] for code in subject_codes
                            if code.casefold() in available_subjects]
                if len(subjects) != len(subject_codes):
                    errors.append(('subject_codes', 'invalid_subject', 'Every subject code must be active in the selected department.'))
                if not errors:
                    academic_row = {
                        'department_id': str(department.id),
                        'department_code': department.code,
                        'batch_id': str(batch.id),
                        'batch_name': batch.name,
                        'subject_ids': [str(subject.id) for subject in subjects],
                        'subject_codes': [subject.code for subject in subjects],
                    }

            # 2. First name validation
            if not first_name:
                errors.append(('first_name', 'missing_first_name', 'First name is required.'))

            # 3. Identifier validation (if provided)
            if role == RoleChoices.STUDENT and not identifier:
                errors.append(('roll_number', 'missing_roll_number', 'Student roll number is required.'))

            if identifier:
                if identifier.casefold() in seen_identifiers_in_file:
                    errors.append(('identifier', 'duplicate_identifier_in_file', f"Duplicate identifier in upload: '{identifier}'"))
                elif identifier.casefold() in existing_identifiers:
                    errors.append(('identifier', 'duplicate_identifier_in_institute', f"Identifier '{identifier}' is already registered in this institute."))
                else:
                    seen_identifiers_in_file.add(identifier.casefold())

            if errors:
                for field_name, error_code, error_message in errors:
                    BulkImportRowError.objects.create(
                        import_job=import_job,
                        row_number=idx,
                        field_name=field_name,
                        error_code=error_code,
                        error_message=error_message,
                        raw_data=row
                    )
            else:
                record = {
                    'row_number': idx,
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'identifier': identifier,
                    'phone_number': phone_number,
                    'role': role
                }
                if academic_row is not None:
                    record.update(academic_row)
                valid_records.append(record)

        import_job.valid_rows = len(valid_records)
        import_job.error_rows = import_job.row_errors.values('row_number').distinct().count()
        import_job.parsed_data = valid_records
        import_job.status = ImportStatus.VALIDATED
        import_job.save()
        return import_job

    @staticmethod
    def _record_file_error(import_job: BulkImportJob, code: str, message: str) -> None:
        import_job.status = ImportStatus.FAILED
        import_job.error_rows = 1
        import_job.save(update_fields=['status', 'error_rows', 'updated_at'])
        BulkImportRowError.objects.create(
            import_job=import_job,
            row_number=1,
            field_name='file',
            error_code=code,
            error_message=message,
        )

    @staticmethod
    def _read_csv(file_obj) -> List[Dict[str, Any]]:
        content = file_obj.read()
        if isinstance(content, bytes):
            content = content.decode('utf-8-sig', errors='replace')
        reader = csv.DictReader(io.StringIO(content))
        # Normalize header keys
        rows = []
        for row in reader:
            normalized_row = {k.strip().lower().replace(' ', '_'): v for k, v in row.items() if k}
            rows.append(normalized_row)
        return rows

    @staticmethod
    def _read_xlsx(file_obj) -> List[Dict[str, Any]]:
        import openpyxl
        wb = openpyxl.load_workbook(file_obj, data_only=True)
        sheet = wb.active
        headers = []
        rows = []
        for idx, row in enumerate(sheet.iter_rows(values_only=True)):
            if idx == 0:
                headers = [str(cell).strip().lower().replace(' ', '_') if cell is not None else '' for cell in row]
            else:
                if not any(row):
                    continue
                row_dict = {}
                for h_idx, h_name in enumerate(headers):
                    if h_name and h_idx < len(row):
                        val = row[h_idx]
                        row_dict[h_name] = str(val).strip() if val is not None else ''
                rows.append(row_dict)
        return rows

    @staticmethod
    @transaction.atomic
    def confirm_import(import_job: BulkImportJob) -> int:
        """
        Commits validated rows to the database atomically.
        Creates User accounts (with first-login password change required)
        and UserInstituteMembership records.
        """
        if import_job.status != ImportStatus.VALIDATED:
            raise ValueError(f"Import job must be in VALIDATED state. Current state: {import_job.status}")

        valid_records = import_job.parsed_data
        created_count = 0

        for record in valid_records:
            email = record['email']
            first_name = record['first_name']
            last_name = record['last_name']
            identifier = record.get('identifier', '')
            phone_number = record.get('phone_number', '')
            role = record.get('role', RoleChoices.STUDENT)

            # Retrieve or create User
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'phone_number': phone_number,
                    'is_verified': False,
                    'must_change_password': True,
                    'is_active': False,
                }
            )
            requires_activation = created or not user.is_verified or not user.has_usable_password()

            if created:
                # Set temporary unusable password until onboarding/activation
                user.set_unusable_password()
                user.save(update_fields=['password'])

            # Create membership
            membership = UserInstituteMembership.objects.create(
                user=user,
                institute=import_job.institute,
                role=role,
                identifier=identifier,
                status=MembershipStatus.INVITED if requires_activation else MembershipStatus.ACTIVE,
                is_verified=not requires_activation,
            )
            if role == RoleChoices.STUDENT:
                from apps.academics.models import Batch, Department, Subject
                from apps.academics.services import configure_student_courses

                configure_student_courses(
                    membership=membership,
                    department=Department.objects.get(pk=record['department_id']),
                    batch=Batch.objects.get(pk=record['batch_id']),
                    subjects=Subject.objects.filter(pk__in=record['subject_ids']),
                )
            if requires_activation:
                send_activation_email(user)
            created_count += 1

        import_job.imported_rows = created_count
        import_job.status = ImportStatus.COMPLETED
        import_job.save(update_fields=['imported_rows', 'status', 'updated_at'])
        return created_count
