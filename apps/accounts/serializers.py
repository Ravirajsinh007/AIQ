from django.contrib.auth import authenticate
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from .models import (
    User,
    Institute,
    UserInstituteMembership,
    RoleChoices,
    MembershipStatus,
    AccountInvitation,
    AccountVerification,
    PasswordResetRequest,
    BulkImportJob,
    BulkImportRowError,
)


class UserInstituteMembershipSerializer(serializers.ModelSerializer):
    institute_code = serializers.CharField(source='institute.code', read_only=True)
    institute_name = serializers.CharField(source='institute.name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    department_name = serializers.SerializerMethodField()
    batch_name = serializers.SerializerMethodField()
    enrolled_subject_codes = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    batch = serializers.SerializerMethodField()
    subject_ids = serializers.SerializerMethodField()

    def _current_placement(self, membership):
        placements = getattr(membership, '_current_academic_placements', None)
        if placements is None:
            from apps.academics.models import PlacementStatus

            placements = membership.academic_placements.filter(
                status=PlacementStatus.ACTIVE,
                effective_end_date__isnull=True,
            ).select_related('program__department', 'batch').order_by('-created_at')
        return next(iter(placements), None)

    def get_department_name(self, membership):
        placement = self._current_placement(membership)
        return placement.program.department.name if placement else None

    def get_batch_name(self, membership):
        placement = self._current_placement(membership)
        return placement.batch.name if placement else None

    def get_department(self, membership):
        placement = self._current_placement(membership)
        return str(placement.program.department_id) if placement else None

    def get_batch(self, membership):
        placement = self._current_placement(membership)
        return str(placement.batch_id) if placement else None

    def get_subject_ids(self, membership):
        placement = self._current_placement(membership)
        if placement is None:
            return []
        enrollments = getattr(membership, '_active_subject_enrollments', None)
        if enrollments is None:
            from apps.academics.models import AcademicStatus

            enrollments = membership.subject_enrollments.filter(
                batch_id=placement.batch_id,
                status=AcademicStatus.ACTIVE,
            )
        return [
            str(enrollment.subject_id)
            for enrollment in enrollments
            if enrollment.batch_id == placement.batch_id
        ]

    def get_enrolled_subject_codes(self, membership):
        placement = self._current_placement(membership)
        if placement is None:
            return []
        enrollments = getattr(membership, '_active_subject_enrollments', None)
        if enrollments is None:
            from apps.academics.models import AcademicStatus

            enrollments = membership.subject_enrollments.filter(
                batch_id=placement.batch_id,
                status=AcademicStatus.ACTIVE,
            ).select_related('subject').order_by('subject__code')
        return [
            enrollment.subject.code
            for enrollment in enrollments
            if enrollment.batch_id == placement.batch_id
        ]

    class Meta:
        model = UserInstituteMembership
        fields = [
            'id',
            'user',
            'user_email',
            'user_name',
            'department_name',
            'batch_name',
            'enrolled_subject_codes',
            'department',
            'batch',
            'subject_ids',
            'institute',
            'institute_code',
            'institute_name',
            'role',
            'exam_permissions',
            'identifier',
            'status',
            'is_verified',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class MembershipUpdateSerializer(serializers.ModelSerializer):
    department = serializers.UUIDField(required=False, write_only=True)
    batch = serializers.UUIDField(required=False, write_only=True)
    subject_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        write_only=True,
    )

    class Meta:
        model = UserInstituteMembership
        fields = [
            'role',
            'exam_permissions',
            'identifier',
            'status',
            'department',
            'batch',
            'subject_ids',
        ]

    def validate_role(self, value):
        if value in (RoleChoices.PLATFORM_ADMIN, RoleChoices.INSTITUTE_ADMIN):
            raise serializers.ValidationError('Administrative roles cannot be assigned through institute membership updates.')
        if self.instance and value != self.instance.role:
            raise serializers.ValidationError('Membership roles cannot be changed through this endpoint.')
        return value

    def validate(self, attrs):
        academic_fields = ('department', 'batch', 'subject_ids')
        if not any(field in attrs for field in academic_fields):
            return attrs
        if (
            attrs.get('department') is None
            and attrs.get('batch') is None
            and attrs.get('subject_ids') == []
        ):
            attrs.pop('subject_ids', None)
            return attrs
        if self.instance.role != RoleChoices.STUDENT:
            raise serializers.ValidationError({
                'department': 'Academic enrollment details can only be updated for students.'
            })
        if not all(field in attrs for field in academic_fields):
            raise serializers.ValidationError({
                'department': 'Department, batch, and subject IDs must be supplied together.'
            })
        if not attrs['subject_ids']:
            raise serializers.ValidationError({
                'subject_ids': 'Select at least one subject for the student.'
            })
        if len(attrs['subject_ids']) != len(set(attrs['subject_ids'])):
            raise serializers.ValidationError({'subject_ids': 'A subject may only be selected once.'})

        from apps.academics.models import AcademicStatus, Batch, Department, Subject

        department = Department.objects.filter(
            pk=attrs['department'],
            institute=self.instance.institute,
            status=AcademicStatus.ACTIVE,
        ).first()
        if department is None:
            raise serializers.ValidationError({'department': 'Select an active department in this institute.'})
        batch = Batch.objects.select_related('program').filter(
            pk=attrs['batch'],
            institute=self.instance.institute,
            status=AcademicStatus.ACTIVE,
            program__department=department,
        ).first()
        if batch is None:
            raise serializers.ValidationError({'batch': 'Select an active batch in the selected department.'})
        subjects = list(Subject.objects.filter(
            pk__in=attrs['subject_ids'],
            institute=self.instance.institute,
            department=department,
            status=AcademicStatus.ACTIVE,
        ))
        if len(subjects) != len(attrs['subject_ids']):
            raise serializers.ValidationError({
                'subject_ids': 'Every selected subject must be active in the selected department and institute.'
            })
        attrs['department_object'] = department
        attrs['batch_object'] = batch
        attrs['subject_objects'] = subjects
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        department = validated_data.pop('department_object', None)
        batch = validated_data.pop('batch_object', None)
        subjects = validated_data.pop('subject_objects', None)
        validated_data.pop('department', None)
        validated_data.pop('batch', None)
        validated_data.pop('subject_ids', None)
        membership = super().update(instance, validated_data)
        if department is not None:
            from apps.academics.services import configure_student_courses

            configure_student_courses(
                membership=membership,
                department=department,
                batch=batch,
                subjects=subjects,
            )
        return membership


class UserSerializer(serializers.ModelSerializer):
    memberships = UserInstituteMembershipSerializer(many=True, read_only=True)
    is_platform_admin = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'first_name',
            'last_name',
            'full_name',
            'phone_number',
            'is_active',
            'is_verified',
            'is_platform_admin',
            'must_change_password',
            'is_staff',
            'memberships',
            'created_at',
        ]
        read_only_fields = ['id', 'is_staff', 'created_at']


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        email = attrs.get('email', '').strip().lower()
        password = attrs.get('password')

        user = authenticate(email=email, password=password)
        if not user:
            raise serializers.ValidationError('Invalid email or password.')

        if not user.is_active:
            raise serializers.ValidationError('Account is deactivated. Please contact your administrator.')

        refresh = RefreshToken.for_user(user)

        return {
            'user': UserSerializer(user).data,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'must_change_password': user.must_change_password,
        }


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, min_length=8, write_only=True)

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate_new_password(self, value):
        old_password = self.initial_data.get('old_password')
        if value == old_password:
            raise serializers.ValidationError('New password must differ from current password.')
        return value

    def save(self):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.must_change_password = False
        user.save(update_fields=['password', 'must_change_password'])
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def save(self):
        email = self.validated_data['email'].strip().lower()
        user = User.objects.filter(email=email, is_active=True).first()
        raw_token = None
        if user:
            request = self.context.get('request')
            ip = request.META.get('REMOTE_ADDR') if request else None
            _, raw_token = PasswordResetRequest.create_request(user=user, ip_address=ip)
        # Always return generic message to prevent email enumeration
        return {
            'message': 'If an active account exists for this email, password reset instructions have been generated.',
            'reset_token': raw_token if self.context.get('include_token_in_test') else None
        }


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)

    def validate(self, attrs):
        email = attrs.get('email', '').strip().lower()
        raw_token = attrs.get('token')
        token_hash = PasswordResetRequest.hash_token(raw_token)

        reset_req = PasswordResetRequest.objects.filter(
            user__email=email,
            token_hash=token_hash,
            used_at__isnull=True,
            expires_at__gt=timezone.now()
        ).select_related('user').first()

        if not reset_req:
            raise serializers.ValidationError('Invalid or expired password reset token.')

        attrs['reset_request'] = reset_req
        attrs['user'] = reset_req.user
        return attrs

    def save(self):
        reset_req = self.validated_data['reset_request']
        user = self.validated_data['user']
        user.set_password(self.validated_data['new_password'])
        user.must_change_password = False
        user.save(update_fields=['password', 'must_change_password'])

        reset_req.used_at = timezone.now()
        reset_req.save(update_fields=['used_at'])
        return user


class AccountVerificationVerifySerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    code = serializers.CharField(required=True, min_length=6, max_length=6)

    def validate(self, attrs):
        email = attrs.get('email', '').strip().lower()
        raw_code = attrs.get('code')
        code_hash = AccountVerification.hash_code(raw_code)

        verification = AccountVerification.objects.filter(
            user__email=email,
            used_at__isnull=True,
            expires_at__gt=timezone.now()
        ).order_by('-created_at').first()

        if not verification:
            raise serializers.ValidationError('No active verification code found for this email.')

        verification.attempts += 1
        verification.save(update_fields=['attempts'])

        if verification.attempts > 5:
            raise serializers.ValidationError('Maximum verification attempts exceeded. Please request a new code.')

        if verification.code_hash != code_hash:
            raise serializers.ValidationError('Invalid verification code.')

        attrs['verification'] = verification
        return attrs


class AccountActivationCompleteSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    code = serializers.CharField(required=True, min_length=6, max_length=6)
    new_password = serializers.CharField(required=True, min_length=8)

    def validate(self, attrs):
        email = attrs.get('email', '').strip().lower()
        raw_code = attrs.get('code')
        code_hash = AccountVerification.hash_code(raw_code)

        verification = AccountVerification.objects.filter(
            user__email=email,
            purpose=AccountVerification.PURPOSE_ACTIVATION,
            used_at__isnull=True,
            expires_at__gt=timezone.now()
        ).order_by('-created_at').first()

        if not verification:
            raise serializers.ValidationError('Invalid or expired activation code.')

        verification.attempts += 1
        verification.save(update_fields=['attempts'])

        if verification.attempts > 5:
            raise serializers.ValidationError('Maximum activation attempts exceeded.')

        if verification.code_hash != code_hash:
            raise serializers.ValidationError('Invalid activation code.')

        attrs['verification'] = verification
        attrs['user'] = verification.user
        return attrs

    def save(self):
        verification = self.validated_data['verification']
        user = self.validated_data['user']
        user.set_password(self.validated_data['new_password'])
        user.is_verified = True
        user.is_active = True
        user.must_change_password = False
        user.save(update_fields=['password', 'is_verified', 'is_active', 'must_change_password'])
        user.memberships.filter(status=MembershipStatus.INVITED).update(
            status=MembershipStatus.ACTIVE,
            is_verified=True,
        )

        verification.used_at = timezone.now()
        verification.save(update_fields=['used_at'])

        # Mark memberships as verified
        user.memberships.update(is_verified=True)
        return user


class InstituteSerializer(serializers.ModelSerializer):
    members_count = serializers.IntegerField(source='memberships.count', read_only=True)

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and not user.is_platform_admin:
            for field_name in ('code', 'name', 'status'):
                fields[field_name].read_only = True
        return fields

    class Meta:
        model = Institute
        fields = [
            'id',
            'code',
            'name',
            'status',
            'contact_email',
            'contact_phone',
            'address',
            'members_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code(self, value):
        normalized = value.strip().upper()
        if not normalized:
            raise serializers.ValidationError('Institute code cannot be empty.')
        existing = Institute.objects.filter(code__iexact=normalized)
        if self.instance:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError('An institute with this code already exists.')
        return normalized


class ProvisionAdminSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    first_name = serializers.CharField(required=True, max_length=150)
    last_name = serializers.CharField(required=True, max_length=150)
    phone_number = serializers.CharField(required=False, allow_blank=True, default='')
    temporary_password = serializers.CharField(required=False, min_length=8)

    def validate_email(self, value):
        email = value.strip().lower()
        institute = self.context['institute']
        # Check if user already exists as admin of this institute
        if UserInstituteMembership.objects.filter(user__email=email, institute=institute).exists():
            raise serializers.ValidationError('This user is already a member of this institute.')
        return email

    def save(self):
        email = self.validated_data['email']
        first_name = self.validated_data['first_name']
        last_name = self.validated_data['last_name']
        phone_number = self.validated_data.get('phone_number', '')
        temp_pwd = self.validated_data.get('temporary_password')
        institute = self.context['institute']

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'first_name': first_name,
                'last_name': last_name,
                'phone_number': phone_number,
                'is_active': True,
                'is_verified': True,
                'must_change_password': True,
            }
        )

        if temp_pwd:
            user.set_password(temp_pwd)
            user.must_change_password = True
            user.save(update_fields=['password', 'must_change_password'])

        membership, _ = UserInstituteMembership.objects.get_or_create(
            user=user,
            institute=institute,
            defaults={
                'role': RoleChoices.INSTITUTE_ADMIN,
                'status': MembershipStatus.ACTIVE,
                'is_verified': True,
            }
        )

        return user, membership


class CreateMemberSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    first_name = serializers.CharField(required=True, max_length=150)
    last_name = serializers.CharField(required=True, max_length=150)
    role = serializers.ChoiceField(
        choices=[RoleChoices.TEACHER, RoleChoices.STUDENT, RoleChoices.EXAM_STAFF],
        default=RoleChoices.STUDENT
    )
    initial_password = serializers.CharField(
        required=True,
        min_length=8,
        write_only=True,
        trim_whitespace=False,
    )
    identifier = serializers.CharField(required=False, allow_blank=True, default='', max_length=100)
    phone_number = serializers.CharField(required=False, allow_blank=True, default='', max_length=32)
    exam_permissions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    department = serializers.UUIDField(required=False, write_only=True)
    batch = serializers.UUIDField(required=False, write_only=True)
    subject_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        write_only=True,
        default=list,
    )

    def validate(self, attrs):
        email = attrs['email'].strip().lower()
        institute = self.context['institute']

        if UserInstituteMembership.objects.filter(user__email=email, institute=institute).exists():
            raise serializers.ValidationError({'email': 'User is already a member of this institute.'})
        existing_user = User.objects.filter(email=email).first()
        if existing_user and not existing_user.is_active:
            raise serializers.ValidationError({
                'email': 'This account is inactive. Contact a platform administrator before adding it.'
            })

        candidate = User(
            email=email,
            first_name=attrs['first_name'],
            last_name=attrs['last_name'],
        )
        try:
            validate_password(attrs['initial_password'], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'initial_password': list(exc.messages)}) from exc

        role = attrs['role']
        identifier = attrs.get('identifier', '').strip()
        if role == RoleChoices.STUDENT:
            identifier = identifier.upper()
            if not identifier:
                raise serializers.ValidationError({'identifier': 'A student roll number is required.'})
            department_id = attrs.get('department')
            batch_id = attrs.get('batch')
            subject_ids = attrs.get('subject_ids', [])
            if not department_id or not batch_id:
                raise serializers.ValidationError({
                    'department': 'Select a department and batch for the student.'
                })
            if not subject_ids:
                raise serializers.ValidationError({
                    'subject_ids': 'Select at least one subject for the student.'
                })
            if len(subject_ids) != len(set(subject_ids)):
                raise serializers.ValidationError({'subject_ids': 'A subject may only be selected once.'})

            from apps.academics.models import AcademicStatus, Batch, Department, Subject

            department = Department.objects.filter(
                pk=department_id,
                institute=institute,
                status=AcademicStatus.ACTIVE,
            ).first()
            if department is None:
                raise serializers.ValidationError({'department': 'Select an active department in this institute.'})
            batch = Batch.objects.select_related('program').filter(
                pk=batch_id,
                institute=institute,
                status=AcademicStatus.ACTIVE,
                program__department=department,
            ).first()
            if batch is None:
                raise serializers.ValidationError({'batch': 'Select an active batch in the selected department.'})
            subjects = list(Subject.objects.filter(
                pk__in=subject_ids,
                institute=institute,
                department=department,
                status=AcademicStatus.ACTIVE,
            ))
            if len(subjects) != len(subject_ids):
                raise serializers.ValidationError({
                    'subject_ids': 'Every selected subject must be active in the selected department and institute.'
                })
            attrs['department_object'] = department
            attrs['batch_object'] = batch
            attrs['subject_objects'] = subjects
        elif attrs.get('department') or attrs.get('batch') or attrs.get('subject_ids'):
            raise serializers.ValidationError({
                'department': 'Department, batch, and subjects can only be assigned to students.'
            })

        if identifier and UserInstituteMembership.objects.filter(
            institute=institute,
            identifier__iexact=identifier,
        ).exists():
            raise serializers.ValidationError({'identifier': f"Identifier '{identifier}' is already taken in this institute."})
        attrs['identifier'] = identifier

        return attrs

    @transaction.atomic
    def save(self):
        email = self.validated_data['email'].strip().lower()
        first_name = self.validated_data['first_name']
        last_name = self.validated_data['last_name']
        role = self.validated_data['role']
        identifier = self.validated_data.get('identifier', '')
        phone_number = self.validated_data.get('phone_number', '')
        exam_permissions = self.validated_data.get('exam_permissions', [])
        institute = self.context['institute']
        department = self.validated_data.get('department_object')
        batch = self.validated_data.get('batch_object')
        subjects = self.validated_data.get('subject_objects', [])

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'first_name': first_name,
                'last_name': last_name,
                'phone_number': phone_number,
                'is_active': True,
                'is_verified': True,
                'must_change_password': True,
            }
        )
        password_was_set = created or not user.has_usable_password() or not user.is_verified
        if password_was_set:
            user.set_password(self.validated_data['initial_password'])
            user.is_active = True
            user.is_verified = True
            user.must_change_password = True
            user.save(update_fields=[
                'password',
                'is_active',
                'is_verified',
                'must_change_password',
            ])

        membership = UserInstituteMembership.objects.create(
            user=user,
            institute=institute,
            role=role,
            identifier=identifier,
            exam_permissions=exam_permissions,
            status=MembershipStatus.ACTIVE,
            is_verified=True,
        )
        membership.initial_password_set = password_was_set
        if role == RoleChoices.STUDENT:
            from apps.academics.services import configure_student_courses

            configure_student_courses(
                membership=membership,
                department=department,
                batch=batch,
                subjects=subjects,
            )
        return membership


class BulkImportRowErrorSerializer(serializers.ModelSerializer):
    class Meta:
        model = BulkImportRowError
        fields = ['id', 'row_number', 'field_name', 'error_code', 'error_message', 'raw_data']


class BulkImportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = BulkImportJob
        fields = [
            'id',
            'institute',
            'import_type',
            'file_name',
            'status',
            'total_rows',
            'valid_rows',
            'error_rows',
            'imported_rows',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class BulkImportJobDetailSerializer(serializers.ModelSerializer):
    row_errors = BulkImportRowErrorSerializer(many=True, read_only=True)

    class Meta:
        model = BulkImportJob
        fields = [
            'id',
            'institute',
            'import_type',
            'file_name',
            'status',
            'total_rows',
            'valid_rows',
            'error_rows',
            'imported_rows',
            'parsed_data',
            'row_errors',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
