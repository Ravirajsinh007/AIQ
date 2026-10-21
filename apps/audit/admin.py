from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'institute', 'actor', 'action', 'resource_type', 'resource_id', 'outcome')
    list_filter = ('action', 'resource_type', 'outcome', 'institute')
    search_fields = ('resource_id', 'actor__email', 'institute__code')
    readonly_fields = (
        'id', 'institute', 'actor', 'action', 'resource_type', 'resource_id',
        'outcome', 'metadata', 'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
