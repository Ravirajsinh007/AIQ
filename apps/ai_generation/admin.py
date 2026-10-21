from django.contrib import admin
from .models import (
    SourceDocument,
    SourceDocumentChunk,
    QuestionGenerationJob,
    GeneratedCandidateRecord,
)


class SourceDocumentChunkInline(admin.TabularInline):
    model = SourceDocumentChunk
    extra = 0
    readonly_fields = ('chunk_index', 'section_title', 'page_number', 'char_count', 'created_at')


@admin.register(SourceDocument)
class SourceDocumentAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'institute', 'subject', 'file_type', 'file_size',
        'processing_status', 'total_pages', 'uploaded_by', 'created_at'
    )
    list_filter = ('institute', 'subject', 'processing_status', 'file_type')
    search_fields = ('title', 'subject__code', 'subject__name')
    readonly_fields = ('file_type', 'file_size', 'processing_status', 'total_pages', 'created_at', 'updated_at')
    inlines = [SourceDocumentChunkInline]


class GeneratedCandidateRecordInline(admin.TabularInline):
    model = GeneratedCandidateRecord
    extra = 0
    readonly_fields = ('candidate_number', 'question_type', 'status', 'persisted_question', 'created_at')


@admin.register(QuestionGenerationJob)
class QuestionGenerationJobAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'institute', 'subject', 'status', 'num_questions_requested',
        'num_questions_generated', 'num_questions_failed_validation', 'requested_by', 'created_at'
    )
    list_filter = ('institute', 'subject', 'status')
    search_fields = ('subject__code', 'subject__name', 'error_message')
    readonly_fields = (
        'num_questions_generated', 'num_questions_failed_validation',
        'safe_diagnostics', 'created_at', 'updated_at'
    )
    inlines = [GeneratedCandidateRecordInline]


@admin.register(GeneratedCandidateRecord)
class GeneratedCandidateRecordAdmin(admin.ModelAdmin):
    list_display = ('job', 'candidate_number', 'question_type', 'status', 'persisted_question', 'created_at')
    list_filter = ('status', 'question_type')
    readonly_fields = ('job', 'candidate_number', 'question_type', 'status', 'candidate_data', 'validation_errors', 'provenance_info', 'created_at')
