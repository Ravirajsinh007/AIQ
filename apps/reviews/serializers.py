from rest_framework import serializers
from apps.questions.models import Question, QuestionStatus
from apps.questions.serializers import QuestionSerializer
from .models import QuestionReviewRecord, ReviewDecision


class QuestionReviewRecordSerializer(serializers.ModelSerializer):
    reviewer_email = serializers.CharField(source='reviewer.email', read_only=True)
    reviewer_name = serializers.SerializerMethodField()
    question_text = serializers.CharField(source='question.question_text', read_only=True)

    class Meta:
        model = QuestionReviewRecord
        fields = [
            'id', 'question', 'question_text', 'reviewer', 'reviewer_email', 'reviewer_name',
            'decision', 'from_status', 'to_status', 'rejection_reason', 'revision_feedback',
            'general_notes', 'rubric_scores', 'question_version', 'created_at'
        ]
        read_only_fields = [
            'id', 'reviewer', 'from_status', 'to_status', 'question_version', 'created_at'
        ]

    def get_reviewer_name(self, obj):
        if obj.reviewer:
            return f"{obj.reviewer.first_name} {obj.reviewer.last_name}".strip() or obj.reviewer.email
        return "Unknown"


class SubmitForReviewActionSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class ApproveQuestionActionSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    rubric_scores = serializers.JSONField(required=False, default=dict)


class RejectQuestionActionSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(required=True, allow_blank=False)
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class RequestRevisionActionSerializer(serializers.Serializer):
    revision_feedback = serializers.CharField(required=True, allow_blank=False)
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class ArchiveQuestionActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class QuestionReviewDetailSerializer(serializers.ModelSerializer):
    """
    Rich serializer providing complete context to the reviewer:
    - Question content, options, answer key, rubrics, source references
    - Complete review decision history
    - Complete version revision history
    - Review workflow actions available
    """
    question = QuestionSerializer(source='*', read_only=True)
    review_history = QuestionReviewRecordSerializer(source='verification_reviews', many=True, read_only=True)

    class Meta:
        model = Question
        fields = ['question', 'review_history']
