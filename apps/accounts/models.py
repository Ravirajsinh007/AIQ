import hashlib
import secrets
import uuid
from datetime import timedelta
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from .managers import UserManager


class RoleChoices(models.TextChoices):
    PLATFORM_ADMIN = 'platform_admin', 'Platform Administrator'
    INSTITUTE_ADMIN = 'institute_admin', 'Institute Administrator'
    TEACHER = 'teacher', 'Teacher'
    STUDENT = 'student', 'Student'
    EXAM_STAFF = 'exam_staff', 'Examination Staff'


class InstituteStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    INACTIVE = 'inactive', 'Inactive'
    SUSPENDED = 'suspended', 'Suspended'


class MembershipStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    INACTIVE = 'inactive', 'Inactive'
    INVITED = 'invited', 'Invited'
    SUSPENDED = 'suspended', 'Suspended'


class InvitationStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    ACCEPTED = 'accepted', 'Accepted'
    EXPIRED = 'expired', 'Expired'
    CANCELLED = 'cancelled', 'Cancelled'


class ImportType(models.TextChoices):
    STUDENTS = 'students', 'Students'
    TEACHERS = 'teachers', 'Teachers'


class ImportStatus(models.TextChoices):
    UPLOADED = 'uploaded', 'Uploaded'
    VALIDATED = 'validated', 'Validated'
    CONFIRMED = 'confirmed', 'Confirmed'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'


class Institute(models.Model):
    """
    Tenant boundary for all academic and user records.
    Created by Platform Administrator.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=InstituteStatus.choices,
        default=InstituteStatus.ACTIVE,
        db_index=True
    )
    contact_email = models.EmailField(blank=True, default='')
    contact_phone = models.CharField(max_length=32, blank=True, default='')
    address = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'institutes_institute'
        ordering = ['name']
        verbose_name = 'Institute'
        verbose_name_plural = 'Institutes'

    def __str__(self):
        return f"{self.name} ({self.code})"


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for ExamCraft AI.
    Uses UUID primary key and normalized email for authentication.
    Supports first-login password enforcement, verification status, and timestamps.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True, max_length=255)
    first_name = models.CharField(max_length=150, blank=True, default='')
    last_name = models.CharField(max_length=150, blank=True, default='')
    phone_number = models.CharField(max_length=32, blank=True, default='')

    # Account lifecycle & security
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)

    # Django internal flags
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    # Timestamps
    date_joined = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        db_table = 'accounts_user'
        ordering = ['-created_at']

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        name = f"{self.first_name} {self.last_name}".strip()
        return name if name else self.email

    @property
    def is_platform_admin(self):
        return self.is_superuser or self.memberships.filter(
            role=RoleChoices.PLATFORM_ADMIN,
            status=MembershipStatus.ACTIVE
        ).exists()

    def get_institute_membership(self, institute_id):
        return self.memberships.filter(
            institute_id=institute_id,
            status=MembershipStatus.ACTIVE
        ).first()


class UserInstituteMembership(models.Model):
    """
    Binds a user to an institute with a strictly controlled role
    and optional examination permissions (setter, moderator, controller).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memberships')
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(
        max_length=30,
        choices=RoleChoices.choices,
        default=RoleChoices.STUDENT,
        db_index=True
    )
    # Scoped permissions for examination staff (e.g., ["setter", "moderator", "controller"])
    exam_permissions = models.JSONField(default=list, blank=True)
    # Unique identifier within institute (roll number or faculty ID)
    identifier = models.CharField(max_length=100, blank=True, default='', db_index=True)
    status = models.CharField(
        max_length=20,
        choices=MembershipStatus.choices,
        default=MembershipStatus.ACTIVE,
        db_index=True
    )
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts_user_institute_membership'
        unique_together = ('user', 'institute')
        indexes = [
            models.Index(fields=['institute', 'role', 'status']),
            models.Index(fields=['institute', 'identifier']),
        ]
        verbose_name = 'User Institute Membership'
        verbose_name_plural = 'User Institute Memberships'

    def __str__(self):
        return f"{self.user.email} - {self.institute.code} ({self.role})"


class AccountInvitation(models.Model):
    """
    Tracks secure onboarding invitations with cryptographically hashed tokens.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(db_index=True)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='invitations')
    role = models.CharField(max_length=30, choices=RoleChoices.choices)
    token_hash = models.CharField(max_length=128, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=InvitationStatus.choices,
        default=InvitationStatus.PENDING,
        db_index=True
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_invitations'
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts_account_invitation'
        ordering = ['-created_at']

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

    @classmethod
    def create_invitation(cls, email: str, institute, role: str, invited_by=None, days_valid: int = 7):
        raw_token = secrets.token_urlsafe(32)
        token_hash = cls.hash_token(raw_token)
        expires_at = timezone.now() + timedelta(days=days_valid)
        invitation = cls.objects.create(
            email=email.strip().lower(),
            institute=institute,
            role=role,
            token_hash=token_hash,
            invited_by=invited_by,
            expires_at=expires_at,
        )
        return invitation, raw_token


class AccountVerification(models.Model):
    """
    Secure verification workflow for account activation and contact verification.
    Stores code hash, tracks expiry, usage, and failed attempts.
    """
    PURPOSE_ACTIVATION = 'activation'
    PURPOSE_CONTACT = 'contact_verify'
    PURPOSE_CHOICES = [
        (PURPOSE_ACTIVATION, 'Account Activation'),
        (PURPOSE_CONTACT, 'Contact Verification'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='verifications')
    code_hash = models.CharField(max_length=128, db_index=True)
    purpose = models.CharField(max_length=30, choices=PURPOSE_CHOICES, default=PURPOSE_ACTIVATION)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'accounts_account_verification'
        ordering = ['-created_at']

    @staticmethod
    def hash_code(raw_code: str) -> str:
        return hashlib.sha256(raw_code.encode('utf-8')).hexdigest()

    @classmethod
    def create_verification(cls, user, purpose: str = PURPOSE_ACTIVATION, minutes_valid: int = 60):
        raw_code = f"{secrets.randbelow(900000) + 100000}"  # 6-digit numeric OTP
        code_hash = cls.hash_code(raw_code)
        expires_at = timezone.now() + timedelta(minutes=minutes_valid)
        verification = cls.objects.create(
            user=user,
            code_hash=code_hash,
            purpose=purpose,
            expires_at=expires_at
        )
        return verification, raw_code


class PasswordResetRequest(models.Model):
    """
    Secure password reset workflow using single-use cryptographically hashed tokens.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_resets')
    token_hash = models.CharField(max_length=128, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'accounts_password_reset_request'
        ordering = ['-created_at']

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

    @classmethod
    def create_request(cls, user, ip_address=None, minutes_valid: int = 30):
        raw_token = secrets.token_urlsafe(32)
        token_hash = cls.hash_token(raw_token)
        expires_at = timezone.now() + timedelta(minutes=minutes_valid)
        obj = cls.objects.create(
            user=user,
            token_hash=token_hash,
            expires_at=expires_at,
            ip_address=ip_address
        )
        return obj, raw_token


class BulkImportJob(models.Model):
    """
    Tracks CSV/XLSX bulk user roster imports per institute with row summary counts.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='import_jobs')
    import_type = models.CharField(max_length=20, choices=ImportType.choices)
    file_name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=ImportStatus.choices,
        default=ImportStatus.UPLOADED,
        db_index=True
    )
    initiated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='initiated_imports'
    )
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    error_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    parsed_data = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts_bulk_import_job'
        ordering = ['-created_at']


class BulkImportRowError(models.Model):
    """
    Stores precise row-level error details for CSV/XLSX imports.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_job = models.ForeignKey(BulkImportJob, on_delete=models.CASCADE, related_name='row_errors')
    row_number = models.PositiveIntegerField()
    field_name = models.CharField(max_length=100, blank=True, default='')
    error_code = models.CharField(max_length=50)
    error_message = models.TextField()
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounts_bulk_import_row_error'
        ordering = ['row_number']
