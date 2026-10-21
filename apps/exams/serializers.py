from rest_framework import serializers

from apps.blueprints.models import GeneratedPaperQuestion, PaperWorkflowStatus
from .permissions import is_exam_manager

from .models import (
    ExamActivityEvent,
    ExamAnswer,
    ExamAnswerEvaluation,
    ExamAttempt,
    ExamIntegrityFlag,
    ExamSchedule,
    IntegrityFlagStatus,
    CodingSubmission,
    HandwrittenAnswerSheet,
    HandwrittenAnswerEvaluation,
    ExamGrievance,
    ExamGrievanceDecision,
    RevaluationDecision,
    RevaluationRequest,
    RevaluationRequestStatus,
)


class ExamScheduleSerializer(serializers.ModelSerializer):
    paper_title = serializers.CharField(source='paper.title', read_only=True)
    subject_code = serializers.CharField(source='paper.subject.code', read_only=True)
    availability_state = serializers.SerializerMethodField()
    batch_name = serializers.CharField(source='batch.name', read_only=True)
    section_name = serializers.CharField(source='section.name', read_only=True, allow_null=True)

    class Meta:
        model = ExamSchedule
        fields = [
            'id', 'institute', 'paper', 'paper_title', 'subject_code', 'batch', 'batch_name',
            'section', 'section_name', 'starts_at', 'ends_at', 'instructions', 'published',
            'revaluation_opens_at', 'revaluation_closes_at',
            'status', 'availability_state', 'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'paper_title', 'subject_code', 'batch_name', 'section_name', 'published',
            'status', 'availability_state', 'created_by', 'created_at', 'updated_at',
        ]

    def get_availability_state(self, obj) -> str:
        return obj.availability_state()

    def validate(self, attrs):
        instance = self.instance
        paper = attrs.get('paper', getattr(instance, 'paper', None))
        institute = attrs.get('institute', getattr(instance, 'institute', None))
        batch = attrs.get('batch', getattr(instance, 'batch', None))
        section = attrs.get('section', getattr(instance, 'section', None))
        if paper and paper.status != 'completed':
            raise serializers.ValidationError({'paper': 'Only completed generated papers can be scheduled.'})
        if paper and paper.workflow_status != PaperWorkflowStatus.RELEASED:
            raise serializers.ValidationError({'paper': 'Only formally released papers can be scheduled for an exam.'})
        if paper and institute and paper.institute_id != institute.id:
            raise serializers.ValidationError({'paper': 'Paper must belong to the scheduled institute.'})
        if batch and institute and batch.institute_id != institute.id:
            raise serializers.ValidationError({'batch': 'Batch must belong to the scheduled institute.'})
        if section and batch and section.batch_id != batch.id:
            raise serializers.ValidationError({'section': 'Section must belong to the selected batch.'})
        starts_at = attrs.get('starts_at', getattr(instance, 'starts_at', None))
        ends_at = attrs.get('ends_at', getattr(instance, 'ends_at', None))
        if starts_at and ends_at and starts_at >= ends_at:
            raise serializers.ValidationError({'ends_at': 'Exam end time must be after the start time.'})
        revaluation_opens_at = attrs.get(
            'revaluation_opens_at', getattr(instance, 'revaluation_opens_at', None)
        )
        revaluation_closes_at = attrs.get(
            'revaluation_closes_at', getattr(instance, 'revaluation_closes_at', None)
        )
        if bool(revaluation_opens_at) != bool(revaluation_closes_at):
            raise serializers.ValidationError({
                'revaluation_closes_at': 'Both revaluation window dates must be set together.'
            })
        if revaluation_opens_at and revaluation_closes_at and revaluation_opens_at >= revaluation_closes_at:
            raise serializers.ValidationError({
                'revaluation_closes_at': 'Revaluation close time must follow its open time.'
            })
        return attrs


class ExamStudentSerializer(serializers.ModelSerializer):
    paper_title = serializers.CharField(source='paper.title', read_only=True)
    subject_code = serializers.CharField(source='paper.subject.code', read_only=True)
    availability_state = serializers.SerializerMethodField()
    batch_name = serializers.CharField(source='batch.name', read_only=True)

    class Meta:
        model = ExamSchedule
        fields = [
            'id', 'paper_title', 'subject_code', 'batch_name', 'starts_at', 'ends_at',
            'instructions', 'availability_state',
        ]

    def get_availability_state(self, obj) -> str:
        return obj.availability_state()


class AttemptSerializer(serializers.ModelSerializer):
    exam_id = serializers.UUIDField(source='exam.id', read_only=True)
    deadline_at = serializers.DateTimeField(read_only=True)
    remaining_seconds = serializers.SerializerMethodField()

    class Meta:
        model = ExamAttempt
        fields = [
            'id', 'exam_id', 'status', 'started_at', 'deadline_at', 'submitted_at',
            'remaining_seconds', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_remaining_seconds(self, obj) -> int:
        from django.utils import timezone

        if obj.status != 'in_progress':
            return 0
        return max(0, int((obj.deadline_at - timezone.now()).total_seconds()))


class DeliveredPaperQuestionSerializer(serializers.ModelSerializer):
    options = serializers.SerializerMethodField()
    coding_config = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedPaperQuestion
        fields = [
            'id', 'section_name', 'section_order', 'question_number',
            'question_type', 'question_text', 'marks', 'options', 'coding_config',
        ]

    def get_options(self, obj):
        safe_options = []
        for option in obj.options_snapshot or []:
            if not isinstance(option, dict):
                continue
            option_key = option.get('option_key', option.get('key'))
            option_text = option.get('option_text', option.get('text'))
            if option_key is not None and option_text is not None:
                safe_options.append({
                    'option_key': option_key,
                    'option_text': option_text,
                    'order': option.get('order'),
                })
        return safe_options

    def get_coding_config(self, obj):
        if obj.question_type != 'coding':
            return None
        config = obj.code_metadata_snapshot
        config = config if isinstance(config, dict) else {}
        safe_config = {}
        language = config.get('language')
        if isinstance(language, str):
            safe_config['language'] = language[:50]
        enabled_languages = config.get('supported_languages') or config.get('languages')
        if isinstance(enabled_languages, list):
            safe_config['supported_languages'] = [
                item[:50] for item in enabled_languages
                if isinstance(item, str) and item
            ][:20]
        starter_template = config.get('starter_template')
        if isinstance(starter_template, str):
            safe_config['starter_template'] = starter_template[:50000]
        constraints = config.get('execution_constraints')
        constraints = constraints if isinstance(constraints, dict) else {}
        safe_constraints = {}
        for key, default, minimum, maximum in (
            ('time_limit_seconds', 3, 1, 15),
            ('memory_limit_mb', 128, 32, 512),
        ):
            value = constraints.get(key, default)
            if isinstance(value, int) and not isinstance(value, bool):
                safe_constraints[key] = min(max(value, minimum), maximum)
            else:
                safe_constraints[key] = default
        safe_config['execution_constraints'] = safe_constraints
        return safe_config


class AnswerWriteSerializer(serializers.Serializer):
    question = serializers.UUIDField()
    response = serializers.JSONField()


class ExamAnswerSerializer(serializers.ModelSerializer):
    question = serializers.UUIDField(source='paper_question_id', read_only=True)
    question_number = serializers.IntegerField(source='paper_question.question_number', read_only=True)

    class Meta:
        model = ExamAnswer
        fields = ['id', 'question', 'question_number', 'response', 'revision', 'created_at', 'updated_at']
        read_only_fields = fields


class ClientActivityEventSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=['visibility_changed', 'fullscreen_exit', 'reconnect'])
    metadata = serializers.JSONField(required=False, default=dict)


class ExamActivityEventSerializer(serializers.ModelSerializer):
    actor_id = serializers.UUIDField(read_only=True, allow_null=True)
    actor_email = serializers.EmailField(source='actor.email', read_only=True, allow_null=True)
    attempt_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = ExamActivityEvent
        fields = ['id', 'attempt_id', 'actor_id', 'actor_email', 'event_type', 'source', 'metadata', 'created_at']
        read_only_fields = fields


class IntegrityFlagSerializer(serializers.ModelSerializer):
    exam_id = serializers.UUIDField(source='attempt.exam_id', read_only=True)
    attempt_id = serializers.UUIDField(read_only=True)
    student_identifier = serializers.CharField(source='attempt.placement.student.identifier', read_only=True)
    student_name = serializers.CharField(source='attempt.placement.student.user.full_name', read_only=True)

    class Meta:
        model = ExamIntegrityFlag
        fields = [
            'id', 'exam_id', 'attempt_id', 'student_identifier', 'student_name', 'code',
            'explanation', 'status', 'review_decision', 'reviewed_by', 'reviewed_at', 'created_at',
        ]
        read_only_fields = fields


class IntegrityFlagReviewSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[IntegrityFlagStatus.REVIEWED, IntegrityFlagStatus.DISMISSED])
    review_decision = serializers.CharField(max_length=2000, allow_blank=False)


class CodingSubmissionWriteSerializer(serializers.Serializer):
    question = serializers.UUIDField()
    code = serializers.CharField(max_length=50000, allow_blank=False)
    language = serializers.CharField(max_length=50, allow_blank=False)


class CodingSubmissionSerializer(serializers.ModelSerializer):
    question = serializers.UUIDField(source='answer.paper_question_id', read_only=True)

    class Meta:
        model = CodingSubmission
        fields = [
            'id', 'question', 'language', 'status', 'submitted_at', 'completed_at',
        ]
        read_only_fields = fields


class ExamAnswerEvaluationSerializer(serializers.ModelSerializer):
    question = serializers.UUIDField(source='answer.paper_question_id', read_only=True)
    question_number = serializers.IntegerField(source='answer.paper_question.question_number', read_only=True)

    class Meta:
        model = ExamAnswerEvaluation
        fields = [
            'question', 'question_number', 'status', 'marks_awarded', 'max_marks',
            'feedback', 'grading_method', 'evaluated_at',
        ]
        read_only_fields = fields


class HandwrittenAnswerSheetUploadSerializer(serializers.Serializer):
    attempt = serializers.UUIDField()
    file = serializers.FileField()

    def validate_file(self, value):
        extension = value.name.rsplit('.', 1)[-1].lower() if '.' in value.name else ''
        if extension not in {'pdf', 'png', 'jpg', 'jpeg'}:
            raise serializers.ValidationError('Only PDF, PNG, and JPEG answer sheets are supported.')
        if value.size <= 0 or value.size > 20 * 1024 * 1024:
            raise serializers.ValidationError('Answer sheet size must be between 1 byte and 20 MB.')
        return value


class HandwrittenAnswerSheetSerializer(serializers.ModelSerializer):
    attempt_id = serializers.UUIDField(read_only=True)
    evaluations = serializers.SerializerMethodField()
    extracted_text = serializers.SerializerMethodField()

    class Meta:
        model = HandwrittenAnswerSheet
        fields = [
            'id', 'attempt_id', 'status', 'extracted_text', 'extraction_error',
            'uploaded_at', 'extracted_at', 'evaluations',
        ]
        read_only_fields = fields

    def get_extracted_text(self, obj):
        user = self.context['request'].user
        if is_exam_manager(user, obj.attempt.exam.institute_id):
            return obj.extracted_text
        return None

    def get_evaluations(self, obj):
        user = self.context['request'].user
        if obj.status != 'reviewed':
            return []
        if user == obj.attempt.placement.student.user or is_exam_manager(user, obj.attempt.exam.institute_id):
            return HandwrittenAnswerEvaluationSerializer(
                obj.evaluations.select_related('paper_question').all(), many=True
            ).data
        return []


class HandwrittenAnswerEvaluationSerializer(serializers.ModelSerializer):
    question = serializers.UUIDField(source='paper_question_id', read_only=True)
    question_number = serializers.IntegerField(source='paper_question.question_number', read_only=True)

    class Meta:
        model = HandwrittenAnswerEvaluation
        fields = ['question', 'question_number', 'marks_awarded', 'max_marks', 'rubric_scores', 'feedback']
        read_only_fields = fields


class HandwrittenReviewItemSerializer(serializers.Serializer):
    question = serializers.UUIDField()
    marks_awarded = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0)
    rubric_scores = serializers.DictField(
        child=serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0),
        required=False,
        default=dict,
    )
    feedback = serializers.CharField(max_length=5000, required=False, allow_blank=True, default='')


class HandwrittenReviewSerializer(serializers.Serializer):
    evaluations = HandwrittenReviewItemSerializer(many=True, allow_empty=False)


class ExamResultQuestionSerializer(serializers.Serializer):
    question = serializers.UUIDField()
    question_number = serializers.IntegerField()
    marks_awarded = serializers.DecimalField(max_digits=7, decimal_places=2)
    max_marks = serializers.DecimalField(max_digits=6, decimal_places=2)
    status = serializers.CharField()
    feedback = serializers.CharField()


class ExamResultSerializer(serializers.Serializer):
    attempt = serializers.UUIDField()
    status = serializers.CharField()
    marks_awarded = serializers.DecimalField(max_digits=8, decimal_places=2)
    max_marks = serializers.DecimalField(max_digits=8, decimal_places=2)
    is_final = serializers.BooleanField()
    questions = ExamResultQuestionSerializer(many=True)


class RevaluationRequestCreateSerializer(serializers.ModelSerializer):
    attempt = serializers.UUIDField()
    question = serializers.UUIDField(source='paper_question_id')

    class Meta:
        model = RevaluationRequest
        fields = ['id', 'attempt', 'question', 'reason', 'status', 'submitted_at']
        read_only_fields = ['id', 'status', 'submitted_at']

    def validate_reason(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('A reason is required.')
        return value


class RevaluationDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=(RevaluationRequestStatus.APPROVED, RevaluationRequestStatus.REJECTED)
    )
    comment = serializers.CharField(max_length=5000, allow_blank=False)
    corrected_marks = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, allow_null=True
    )

    def validate(self, attrs):
        if attrs['decision'] == RevaluationRequestStatus.REJECTED and attrs.get('corrected_marks') is not None:
            raise serializers.ValidationError({
                'corrected_marks': 'Corrected marks can only be supplied for an approved request.'
            })
        return attrs


class RevaluationDecisionHistorySerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source='reviewer.full_name', read_only=True)

    class Meta:
        model = RevaluationDecision
        fields = [
            'id', 'reviewer_name', 'decision', 'comment', 'previous_marks',
            'corrected_marks', 'created_at',
        ]
        read_only_fields = fields


class RevaluationRequestSerializer(serializers.ModelSerializer):
    question = serializers.UUIDField(source='paper_question_id', read_only=True)
    question_number = serializers.IntegerField(source='paper_question.question_number', read_only=True)
    decisions = RevaluationDecisionHistorySerializer(many=True, read_only=True)

    class Meta:
        model = RevaluationRequest
        fields = [
            'id', 'attempt', 'question', 'question_number', 'reason', 'status',
            'review_comment', 'corrected_marks', 'submitted_at', 'decided_at', 'decisions',
        ]
        read_only_fields = fields


class ExamGrievanceCreateSerializer(serializers.Serializer):
    attempt = serializers.UUIDField()
    reason = serializers.CharField(max_length=5000)

    def validate_reason(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('A reason is required.')
        return value


class ExamGrievanceDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=(RevaluationRequestStatus.APPROVED, RevaluationRequestStatus.REJECTED)
    )
    comment = serializers.CharField(max_length=5000, allow_blank=False)


class ExamGrievanceDecisionHistorySerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source='reviewer.full_name', read_only=True)

    class Meta:
        model = ExamGrievanceDecision
        fields = ['id', 'reviewer_name', 'decision', 'comment', 'created_at']
        read_only_fields = fields


class ExamGrievanceSerializer(serializers.ModelSerializer):
    decisions = ExamGrievanceDecisionHistorySerializer(many=True, read_only=True)

    class Meta:
        model = ExamGrievance
        fields = [
            'id', 'attempt', 'reason', 'status', 'review_comment',
            'filed_at', 'decided_at', 'decisions',
        ]
        read_only_fields = fields
