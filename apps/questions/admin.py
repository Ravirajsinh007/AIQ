from django.contrib import admin
from .models import (
    Question,
    QuestionOption,
    AnswerKey,
    QuestionRubric,
    QuestionSourceReference,
    QuestionVersion,
    QuestionTag,
    QuestionReview,
)


class QuestionOptionInline(admin.TabularInline):
    model = QuestionOption
    extra = 0


class AnswerKeyInline(admin.StackedInline):
    model = AnswerKey
    can_delete = False
    max_num = 1


class QuestionRubricInline(admin.TabularInline):
    model = QuestionRubric
    extra = 0


class QuestionSourceReferenceInline(admin.TabularInline):
    model = QuestionSourceReference
    extra = 0


class QuestionVersionInline(admin.TabularInline):
    model = QuestionVersion
    extra = 0
    readonly_fields = ('version_number', 'snapshot_data', 'changed_by', 'change_reason', 'created_at')


class QuestionReviewInline(admin.TabularInline):
    model = QuestionReview
    extra = 0
    readonly_fields = ('reviewer', 'decision', 'comment', 'created_at')


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'subject', 'question_type', 'difficulty', 'marks',
        'bloom_taxonomy', 'status', 'current_version', 'created_by', 'created_at'
    )
    list_filter = ('institute', 'subject', 'question_type', 'difficulty', 'status', 'bloom_taxonomy')
    search_fields = ('question_text', 'subject__code', 'subject__name')
    readonly_fields = ('current_version', 'created_at', 'updated_at')
    inlines = [
        QuestionOptionInline,
        AnswerKeyInline,
        QuestionRubricInline,
        QuestionSourceReferenceInline,
        QuestionVersionInline,
        QuestionReviewInline,
    ]


@admin.register(QuestionTag)
class QuestionTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'institute', 'slug', 'created_at')
    list_filter = ('institute',)
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(QuestionVersion)
class QuestionVersionAdmin(admin.ModelAdmin):
    list_display = ('question', 'version_number', 'changed_by', 'created_at')
    list_filter = ('question__institute',)
    readonly_fields = ('question', 'version_number', 'snapshot_data', 'changed_by', 'change_reason', 'created_at')


@admin.register(QuestionSourceReference)
class QuestionSourceReferenceAdmin(admin.ModelAdmin):
    list_display = ('source_title', 'question', 'page_or_section', 'created_at')
    search_fields = ('source_title', 'excerpt')


@admin.register(QuestionReview)
class QuestionReviewAdmin(admin.ModelAdmin):
    list_display = ('question', 'reviewer', 'decision', 'created_at')
    list_filter = ('decision',)
    search_fields = ('comment',)
