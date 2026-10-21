from django.contrib import admin

from .models import ExamActivityEvent, ExamAnswer, ExamAttempt, ExamIntegrityFlag, ExamSchedule


@admin.register(ExamSchedule)
class ExamScheduleAdmin(admin.ModelAdmin):
    list_display = ('paper', 'institute', 'batch', 'starts_at', 'ends_at', 'published', 'status')
    list_filter = ('institute', 'published', 'status')
    search_fields = ('paper__title', 'batch__name')
    readonly_fields = tuple(field.name for field in ExamSchedule._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ('id', 'exam', 'placement', 'status', 'started_at', 'submitted_at')
    list_filter = ('status', 'exam__institute')
    readonly_fields = tuple(field.name for field in ExamAttempt._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ExamAnswer)
class ExamAnswerAdmin(admin.ModelAdmin):
    list_display = ('attempt', 'paper_question', 'revision', 'updated_at')
    readonly_fields = tuple(field.name for field in ExamAnswer._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ExamActivityEvent)
class ExamActivityEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'source', 'institute', 'attempt', 'actor', 'created_at')
    list_filter = ('event_type', 'source', 'institute')
    readonly_fields = tuple(field.name for field in ExamActivityEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ExamIntegrityFlag)
class ExamIntegrityFlagAdmin(admin.ModelAdmin):
    list_display = ('attempt', 'code', 'status', 'reviewed_by', 'created_at')
    list_filter = ('status', 'code', 'attempt__exam__institute')
    readonly_fields = tuple(field.name for field in ExamIntegrityFlag._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
