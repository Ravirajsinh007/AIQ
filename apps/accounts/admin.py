from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    User,
    Institute,
    UserInstituteMembership,
    AccountInvitation,
    AccountVerification,
    PasswordResetRequest,
    BulkImportJob,
    BulkImportRowError,
)

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'is_active', 'is_verified', 'must_change_password', 'is_staff')
    list_filter = ('is_active', 'is_verified', 'is_staff', 'is_superuser')
    search_fields = ('email', 'first_name', 'last_name', 'phone_number')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'date_joined')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'phone_number')}),
        ('Status & Security', {'fields': ('is_active', 'is_verified', 'must_change_password')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Metadata', {'fields': ('id', 'date_joined', 'created_at', 'updated_at')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'first_name', 'last_name', 'is_active', 'is_verified'),
        }),
    )


@admin.register(Institute)
class InstituteAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'status', 'contact_email', 'created_at')
    list_filter = ('status',)
    search_fields = ('code', 'name', 'contact_email')
    ordering = ('name',)


@admin.register(UserInstituteMembership)
class UserInstituteMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'institute', 'role', 'status', 'identifier', 'is_verified', 'created_at')
    list_filter = ('role', 'status', 'institute')
    search_fields = ('user__email', 'identifier', 'institute__name')


@admin.register(AccountInvitation)
class AccountInvitationAdmin(admin.ModelAdmin):
    list_display = ('email', 'institute', 'role', 'status', 'expires_at', 'created_at')
    list_filter = ('status', 'role', 'institute')
    search_fields = ('email',)


@admin.register(AccountVerification)
class AccountVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'purpose', 'attempts', 'expires_at', 'used_at', 'created_at')
    list_filter = ('purpose',)


@admin.register(PasswordResetRequest)
class PasswordResetRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'expires_at', 'used_at', 'ip_address', 'created_at')
    search_fields = ('user__email',)


class BulkImportRowErrorInline(admin.TabularInline):
    model = BulkImportRowError
    extra = 0
    readonly_fields = ('row_number', 'field_name', 'error_code', 'error_message', 'raw_data')


@admin.register(BulkImportJob)
class BulkImportJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'institute', 'import_type', 'file_name', 'status', 'total_rows', 'valid_rows', 'error_rows', 'imported_rows', 'created_at')
    list_filter = ('status', 'import_type', 'institute')
    inlines = [BulkImportRowErrorInline]
