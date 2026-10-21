from django.contrib import admin
from .models import (
    PaperBlueprint,
    BlueprintSection,
    BlueprintRule,
    GeneratedPaper,
    GeneratedPaperQuestion,
)


class BlueprintRuleInline(admin.TabularInline):
    model = BlueprintRule
    extra = 0


class BlueprintSectionInline(admin.StackedInline):
    model = BlueprintSection
    extra = 0


@admin.register(PaperBlueprint)
class PaperBlueprintAdmin(admin.ModelAdmin):
    list_display = ('title', 'institute', 'subject', 'total_marks', 'duration_minutes', 'status', 'created_by', 'created_at')
    list_filter = ('institute', 'status', 'subject')
    search_fields = ('title', 'subject__code', 'subject__name')
    inlines = [BlueprintSectionInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='blueprint.updated' if change else 'blueprint.created',
            resource_type='paper_blueprint',
            resource_id=obj.pk,
            actor=request.user,
            institute=obj.institute,
        )

    def delete_model(self, request, obj):
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='blueprint.deleted',
            resource_type='paper_blueprint',
            resource_id=obj.pk,
            actor=request.user,
            institute=obj.institute,
        )
        super().delete_model(request, obj)


@admin.register(BlueprintSection)
class BlueprintSectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'blueprint', 'order', 'target_marks')
    list_filter = ('blueprint__institute',)
    search_fields = ('name', 'blueprint__title')
    inlines = [BlueprintRuleInline]


@admin.register(BlueprintRule)
class BlueprintRuleAdmin(admin.ModelAdmin):
    list_display = ('section', 'order', 'question_type', 'question_count', 'marks_per_question', 'difficulty')
    list_filter = ('question_type', 'difficulty', 'bloom_taxonomy')


class GeneratedPaperQuestionInline(admin.TabularInline):
    model = GeneratedPaperQuestion
    extra = 0
    readonly_fields = (
        'section_name', 'section_order', 'question_number', 'question',
        'question_version', 'question_type', 'question_text', 'marks',
        'difficulty', 'bloom_taxonomy', 'created_at'
    )


@admin.register(GeneratedPaper)
class GeneratedPaperAdmin(admin.ModelAdmin):
    list_display = ('title', 'blueprint', 'institute', 'subject', 'total_marks', 'status', 'generation_version', 'created_at')
    list_filter = ('institute', 'status', 'subject')
    search_fields = ('title', 'blueprint__title')
    readonly_fields = (
        'id', 'institute', 'blueprint', 'title', 'subject', 'total_marks',
        'duration_minutes', 'status', 'workflow_status', 'generation_version',
        'blueprint_snapshot', 'validation_report', 'created_by', 'submitted_at',
        'approved_by', 'approved_at', 'rejection_reason', 'scheduled_release_at',
        'released_at', 'archived_at', 'supersedes', 'amendment_reason',
        'created_at', 'updated_at',
    )
    inlines = [GeneratedPaperQuestionInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(GeneratedPaperQuestion)
class GeneratedPaperQuestionAdmin(admin.ModelAdmin):
    list_display = ('paper', 'section_name', 'question_number', 'question_type', 'marks')
    list_filter = ('question_type', 'difficulty')
    readonly_fields = (
        'paper', 'section_name', 'section_order', 'question_number',
        'question', 'question_version', 'question_type', 'question_text',
        'marks', 'negative_marks', 'difficulty', 'bloom_taxonomy',
        'options_snapshot', 'rubric_snapshot', 'provenance_snapshot',
        'test_cases_snapshot', 'code_metadata_snapshot', 'created_at'
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
