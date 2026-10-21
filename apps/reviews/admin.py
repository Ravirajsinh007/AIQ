from django.contrib import admin
from .models import QuestionReviewRecord


@admin.register(QuestionReviewRecord)
class QuestionReviewRecordAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'question', 'reviewer', 'decision',
        'from_status', 'to_status', 'question_version', 'created_at'
    )
    list_filter = ('decision', 'from_status', 'to_status', 'created_at')
    search_fields = (
        'question__question_text', 'reviewer__email',
        'rejection_reason', 'revision_feedback', 'general_notes'
    )
    readonly_fields = (
        'id', 'question', 'reviewer', 'decision', 'from_status',
        'to_status', 'rejection_reason', 'revision_feedback',
        'general_notes', 'rubric_scores', 'question_version', 'created_at'
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
