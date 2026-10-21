import csv
import io
import re
from typing import Tuple, List, Dict, Any
from django.db import transaction
from django.utils import timezone
from .models import (
    User,
    Institute,
    UserInstituteMembership,
    RoleChoices,
    MembershipStatus,
    BulkImportJob,
    BulkImportRowError,
    ImportStatus,
    ImportType,
)

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')


class BulkImportService:
    """
    Handles CSV and XLSX bulk parsing, row-level validation, duplicate detection,
    and database commit upon confirmation.
    """

    @staticmethod
    def parse_and_validate(import_job: BulkImportJob, file_obj) -> BulkImportJob:
        filename = import_job.file_name.lower()
        rows: List[Dict[str, Any]] = []

        if filename.endswith('.csv'):
            rows = BulkImportService._read_csv(file_obj)
        elif filename.endswith(('.xlsx', '.xls')):
            rows = BulkImportService._read_xlsx(file_obj)
        else:
            import_job.status = ImportStatus.FAILED
            import_job.save(update_fields=['status'])
            BulkImportRowError.objects.create(
                import_job=import_job,
                row_number=0,
                field_name='file',
                error_code='unsupported_format',
                error_message='Unsupported file format. Please upload a .csv or .xlsx file.'
            )
            return import_job

        import_job.total_rows = len(rows)
        valid_records: List[Dict[str, Any]] = []
        seen_emails_in_file = set()
        seen_identifiers_in_file = set()

        # Existing members for this institute
        existing_emails = set(
            UserInstituteMembership.objects.filter(
                institute=import_job.institute
            ).values_list('user__email', flat=True)
        )
        existing_identifiers = set(
            UserInstituteMembership.objects.filter(
                institute=import_job.institute
            ).exclude(identifier='').values_list('identifier', flat=True)
        )

        role = RoleChoices.STUDENT if import_job.import_type == ImportType.STUDENTS else RoleChoices.TEACHER

        for idx, row in enumerate(rows, start=2):  # Row 1 is header
            errors = []
            email = str(row.get('email', '')).strip().lower()
            first_name = str(row.get('first_name', '')).strip()
            last_name = str(row.get('last_name', '')).strip()
            identifier = str(row.get('identifier', row.get('roll_number', row.get('employee_id', '')))).strip()
            phone_number = str(row.get('phone_number', '')).strip()

            # 1. Email validation
            if not email:
                errors.append(('email', 'missing_email', 'Email address is required.'))
            elif not EMAIL_REGEX.match(email):
                errors.append(('email', 'invalid_email', f"Invalid email format: '{email}'"))
            elif email in seen_emails_in_file:
                errors.append(('email', 'duplicate_in_file', f"Duplicate email in upload: '{email}'"))
            elif email in existing_emails:
                errors.append(('email', 'duplicate_in_institute', f"User with email '{email}' is already a member of this institute."))

            # 2. First name validation
            if not first_name:
                errors.append(('first_name', 'missing_first_name', 'First name is required.'))

            # 3. Identifier validation (if provided)
            if identifier:
                if identifier in seen_identifiers_in_file:
                    errors.append(('identifier', 'duplicate_identifier_in_file', f"Duplicate identifier in upload: '{identifier}'"))
                elif identifier in existing_identifiers:
                    errors.append(('identifier', 'duplicate_identifier_in_institute', f"Identifier '{identifier}' is already registered in this institute."))

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
                seen_emails_in_file.add(email)
                if identifier:
                    seen_identifiers_in_file.add(identifier)

                valid_records.append({
                    'row_number': idx,
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'identifier': identifier,
                    'phone_number': phone_number,
                    'role': role
                })

        import_job.valid_rows = len(valid_records)
        import_job.error_rows = import_job.row_errors.values('row_number').distinct().count()
        import_job.parsed_data = valid_records
        import_job.status = ImportStatus.VALIDATED
        import_job.save()
        return import_job

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
                    'is_active': True,
                    'is_verified': False,
                    'must_change_password': True,
                }
            )

            if created:
                # Set temporary unusable password until onboarding/activation
                user.set_unusable_password()
                user.save(update_fields=['password'])

            # Create membership
            UserInstituteMembership.objects.create(
                user=user,
                institute=import_job.institute,
                role=role,
                identifier=identifier,
                status=MembershipStatus.ACTIVE,
                is_verified=False
            )
            created_count += 1

        import_job.imported_rows = created_count
        import_job.status = ImportStatus.COMPLETED
        import_job.save(update_fields=['imported_rows', 'status', 'updated_at'])
        return created_count
