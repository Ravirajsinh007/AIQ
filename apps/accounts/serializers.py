from django.contrib.auth import authenticate
from django.utils import timezone
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

    class Meta:
        model = UserInstituteMembership
        fields = [
            'id',
            'user',
            'user_email',
            'user_name',
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
    class Meta:
        model = UserInstituteMembership
        fields = ['role', 'exam_permissions', 'identifier', 'status']

    def validate_role(self, value):
        if value == RoleChoices.PLATFORM_ADMIN:
            raise serializers.ValidationError('Platform administrator access cannot be assigned through institute membership updates.')
        return value


class UserSerializer(serializers.ModelSerializer):
    memberships = UserInstituteMembershipSerializer(many=True, read_only=True)

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

        verification.used_at = timezone.now()
        verification.save(update_fields=['used_at'])

        # Mark memberships as verified
        user.memberships.update(is_verified=True)
        return user


class InstituteSerializer(serializers.ModelSerializer):
    members_count = serializers.IntegerField(source='memberships.count', read_only=True)

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
    identifier = serializers.CharField(required=False, allow_blank=True, default='', max_length=100)
    phone_number = serializers.CharField(required=False, allow_blank=True, default='', max_length=32)
    exam_permissions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )

    def validate(self, attrs):
        email = attrs['email'].strip().lower()
        institute = self.context['institute']

        if UserInstituteMembership.objects.filter(user__email=email, institute=institute).exists():
            raise serializers.ValidationError({'email': 'User is already a member of this institute.'})

        identifier = attrs.get('identifier', '').strip()
        if identifier and UserInstituteMembership.objects.filter(institute=institute, identifier=identifier).exists():
            raise serializers.ValidationError({'identifier': f"Identifier '{identifier}' is already taken in this institute."})

        return attrs

    def save(self):
        email = self.validated_data['email'].strip().lower()
        first_name = self.validated_data['first_name']
        last_name = self.validated_data['last_name']
        role = self.validated_data['role']
        identifier = self.validated_data.get('identifier', '')
        phone_number = self.validated_data.get('phone_number', '')
        exam_permissions = self.validated_data.get('exam_permissions', [])
        institute = self.context['institute']

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
            user.set_unusable_password()
            user.save(update_fields=['password'])

        membership = UserInstituteMembership.objects.create(
            user=user,
            institute=institute,
            role=role,
            identifier=identifier,
            exam_permissions=exam_permissions,
            status=MembershipStatus.ACTIVE,
            is_verified=False
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
