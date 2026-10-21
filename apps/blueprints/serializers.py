from decimal import Decimal

from rest_framework import serializers
from apps.accounts.models import Institute
from apps.academics.models import Subject, Unit, Topic, LearningOutcome
from apps.questions.models import QuestionType, DifficultyLevel, BloomTaxonomy
from .models import (
    PaperBlueprint,
    BlueprintSection,
    BlueprintRule,
    GeneratedPaper,
    GeneratedPaperQuestion,
    BlueprintStatus,
    GeneratedPaperStatus,
    PaperWorkflowStatus,
)


class BlueprintRuleSerializer(serializers.ModelSerializer):
    unit_title = serializers.CharField(source='unit.title', read_only=True)
    topic_title = serializers.CharField(source='topic.title', read_only=True)
    learning_outcome_code = serializers.CharField(source='learning_outcome.code', read_only=True)
    total_rule_marks = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)

    class Meta:
        model = BlueprintRule
        fields = [
            'id', 'section', 'order', 'question_type', 'question_count',
            'marks_per_question', 'total_rule_marks', 'unit', 'unit_title',
            'topic', 'topic_title', 'learning_outcome', 'learning_outcome_code',
            'difficulty', 'bloom_taxonomy', 'difficulty_distribution',
            'bloom_taxonomy_distribution', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class BlueprintSectionSerializer(serializers.ModelSerializer):
    rules = BlueprintRuleSerializer(many=True, read_only=True)

    class Meta:
        model = BlueprintSection
        fields = [
            'id', 'blueprint', 'name', 'order', 'instructions', 'target_marks',
            'rules', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PaperBlueprintListSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True)

    class Meta:
        model = PaperBlueprint
        fields = [
            'id', 'institute', 'title', 'subject', 'subject_code', 'subject_name',
            'academic_year', 'semester', 'program', 'department', 'total_marks',
            'duration_minutes', 'status', 'allow_question_reuse',
            'created_by', 'created_by_email', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class PaperBlueprintDetailSerializer(serializers.ModelSerializer):
    sections = BlueprintSectionSerializer(many=True, read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True)

    class Meta:
        model = PaperBlueprint
        fields = [
            'id', 'institute', 'title', 'subject', 'subject_code', 'subject_name',
            'academic_year', 'semester', 'program', 'department', 'total_marks',
            'duration_minutes', 'status', 'allow_question_reuse',
            'general_instructions', 'sections', 'created_by', 'created_by_email',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class GeneratePaperRequestSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)


class GeneratedPaperQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneratedPaperQuestion
        fields = [
            'id', 'section_name', 'section_order', 'question_number',
            'question', 'question_version', 'question_type', 'question_text',
            'marks', 'negative_marks', 'difficulty', 'bloom_taxonomy',
            'options_snapshot', 'rubric_snapshot', 'provenance_snapshot', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class GeneratedPaperListSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    blueprint_title = serializers.CharField(source='blueprint.title', read_only=True)
    question_count = serializers.IntegerField(source='paper_questions.count', read_only=True)

    class Meta:
        model = GeneratedPaper
        fields = [
            'id', 'institute', 'blueprint', 'blueprint_title', 'title',
            'subject', 'subject_code', 'subject_name', 'total_marks',
            'duration_minutes', 'status', 'workflow_status', 'generation_version', 'question_count',
            'scheduled_release_at', 'released_at', 'supersedes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'status', 'generation_version', 'created_at', 'updated_at']


class GeneratedPaperDetailSerializer(serializers.ModelSerializer):
    paper_questions = GeneratedPaperQuestionSerializer(many=True, read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    blueprint_title = serializers.CharField(source='blueprint.title', read_only=True)

    class Meta:
        model = GeneratedPaper
        fields = [
            'id', 'institute', 'blueprint', 'blueprint_title', 'title',
            'subject', 'subject_code', 'subject_name', 'total_marks',
            'duration_minutes', 'status', 'workflow_status', 'generation_version',
            'submitted_at', 'approved_by', 'approved_at', 'rejection_reason',
            'scheduled_release_at', 'released_at', 'archived_at', 'supersedes',
            'amendment_reason',
            'blueprint_snapshot', 'validation_report', 'paper_questions',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'status', 'workflow_status', 'generation_version', 'submitted_at',
            'approved_by', 'approved_at', 'rejection_reason', 'scheduled_release_at',
            'released_at', 'archived_at', 'supersedes', 'amendment_reason',
            'blueprint_snapshot', 'validation_report', 'created_at', 'updated_at'
        ]


class PaperRejectionSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(max_length=4000, allow_blank=False)


class PaperReleaseScheduleSerializer(serializers.Serializer):
    release_at = serializers.DateTimeField()


class PaperQuestionAmendmentSerializer(serializers.Serializer):
    question_number = serializers.IntegerField(min_value=1)
    question_text = serializers.CharField(required=False, allow_blank=False)
    marks = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, min_value=Decimal('0.01')
    )
    negative_marks = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, min_value=Decimal('0.00')
    )
    options_snapshot = serializers.ListField(
        child=serializers.DictField(), required=False
    )
    rubric_snapshot = serializers.ListField(
        child=serializers.DictField(), required=False
    )


class PaperAmendmentSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=4000, allow_blank=False)
    question_edits = PaperQuestionAmendmentSerializer(many=True, required=False, default=list)

    def validate_question_edits(self, value):
        numbers = [item['question_number'] for item in value]
        if len(numbers) != len(set(numbers)):
            raise serializers.ValidationError('Each question number may only be amended once.')
        for item in value:
            if (
                'marks' in item
                and 'negative_marks' in item
                and item['negative_marks'] > item['marks']
            ):
                raise serializers.ValidationError('Negative marks cannot exceed marks.')
        return value
