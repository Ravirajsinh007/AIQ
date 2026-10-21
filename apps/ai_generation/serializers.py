from decimal import Decimal
from rest_framework import serializers
from apps.accounts.models import Institute
from apps.academics.models import Subject, Unit, Topic, LearningOutcome
from apps.questions.models import QuestionType
from .models import (
    SourceDocument,
    SourceDocumentChunk,
    QuestionGenerationJob,
    GeneratedCandidateRecord,
    DocumentType,
)


class SourceDocumentChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceDocumentChunk
        fields = [
            'id', 'document', 'chunk_index', 'section_title',
            'page_number', 'content', 'char_count', 'created_at'
        ]
        read_only_fields = ['id', 'char_count', 'created_at']


class SourceDocumentSerializer(serializers.ModelSerializer):
    institute_code = serializers.CharField(source='institute.code', read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    uploaded_by_email = serializers.CharField(source='uploaded_by.email', read_only=True)
    chunks_count = serializers.IntegerField(source='chunks.count', read_only=True)

    class Meta:
        model = SourceDocument
        fields = [
            'id', 'institute', 'institute_code', 'subject', 'subject_code', 'subject_name',
            'unit', 'topic', 'title', 'file', 'file_type', 'file_size',
            'processing_status', 'error_message', 'total_pages', 'chunks_count',
            'uploaded_by', 'uploaded_by_email', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'file_type', 'file_size', 'processing_status',
            'error_message', 'total_pages', 'uploaded_by', 'created_at', 'updated_at'
        ]


class SourceDocumentUploadSerializer(serializers.ModelSerializer):
    file = serializers.FileField(required=True)

    class Meta:
        model = SourceDocument
        fields = ['id', 'institute', 'subject', 'unit', 'topic', 'title', 'file']
        read_only_fields = ['id']

    def validate(self, attrs):
        inst = attrs.get('institute')
        subj = attrs.get('subject')
        unit = attrs.get('unit')
        topic = attrs.get('topic')
        f = attrs.get('file')

        if subj and inst and subj.institute_id != inst.id:
            raise serializers.ValidationError({'subject': 'Subject must belong to the selected institute.'})
        if unit and subj and unit.subject_id != subj.id:
            raise serializers.ValidationError({'unit': 'Unit must belong to the selected subject.'})
        if topic and not unit:
            raise serializers.ValidationError({'unit': 'A unit is required when a topic is selected.'})
        if topic and unit and topic.unit_id != unit.id:
            raise serializers.ValidationError({'topic': 'Topic must belong to the selected unit.'})

        # File validation
        if f:
            name = f.name
            ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
            if ext not in ['pdf', 'docx', 'txt']:
                raise serializers.ValidationError({
                    'file': f"Unsupported file extension '.{ext}'. Supported formats: PDF, DOCX, TXT."
                })
            if f.size > 15 * 1024 * 1024:
                raise serializers.ValidationError({'file': 'File size exceeds maximum allowable limit of 15MB.'})

        return attrs


class QuestionGenerationJobRequestSerializer(serializers.Serializer):
    institute = serializers.PrimaryKeyRelatedField(queryset=Institute.objects.all())
    subject = serializers.PrimaryKeyRelatedField(queryset=Subject.objects.all())
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all(), required=False, allow_null=True)
    topic = serializers.PrimaryKeyRelatedField(queryset=Topic.objects.all(), required=False, allow_null=True)
    learning_outcome = serializers.PrimaryKeyRelatedField(
        queryset=LearningOutcome.objects.all(),
        required=False,
        allow_null=True
    )
    source_document_ids = serializers.PrimaryKeyRelatedField(
        queryset=SourceDocument.objects.all(),
        many=True,
        required=False
    )
    question_types = serializers.ListField(
        child=serializers.ChoiceField(choices=QuestionType.choices),
        required=False,
        default=['mcq']
    )
    num_questions = serializers.IntegerField(required=False, default=5, min_value=1, max_value=20)
    difficulty_distribution = serializers.DictField(required=False, default=dict)
    bloom_taxonomy_distribution = serializers.DictField(required=False, default=dict)
    default_marks = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=Decimal('1.00'))
    default_negative_marks = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=Decimal('0.00'))
    language = serializers.CharField(max_length=50, required=False, default='English')

    def validate(self, attrs):
        inst = attrs['institute']
        subj = attrs['subject']
        unit = attrs.get('unit')
        topic = attrs.get('topic')
        lo = attrs.get('learning_outcome')
        docs = attrs.get('source_document_ids', [])

        if subj.institute_id != inst.id:
            raise serializers.ValidationError({'subject': 'Subject must belong to the specified institute.'})
        if unit and unit.subject_id != subj.id:
            raise serializers.ValidationError({'unit': 'Unit must belong to the selected subject.'})
        if topic and not unit:
            raise serializers.ValidationError({'unit': 'A unit is required when a topic is selected.'})
        if topic and unit and topic.unit_id != unit.id:
            raise serializers.ValidationError({'topic': 'Topic must belong to the selected unit.'})
        if lo and lo.subject_id != subj.id:
            raise serializers.ValidationError({'learning_outcome': 'Learning outcome must belong to the selected subject.'})

        for doc in docs:
            if doc.institute_id != inst.id:
                raise serializers.ValidationError({
                    'source_document_ids': f"Document '{doc.title}' belongs to another institute."
                })
            if doc.subject_id != subj.id:
                raise serializers.ValidationError({
                    'source_document_ids': f"Document '{doc.title}' is not mapped to subject '{subj.code}'."
                })
            if doc.processing_status != 'completed':
                raise serializers.ValidationError({
                    'source_document_ids': f"Document '{doc.title}' has not completed text processing."
                })

        return attrs


class QuestionGenerationJobSerializer(serializers.ModelSerializer):
    institute_code = serializers.CharField(source='institute.code', read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    requested_by_email = serializers.CharField(source='requested_by.email', read_only=True)

    class Meta:
        model = QuestionGenerationJob
        fields = [
            'id', 'institute', 'institute_code', 'subject', 'subject_code', 'subject_name',
            'unit', 'topic', 'learning_outcome', 'status', 'question_types',
            'num_questions_requested', 'num_questions_generated', 'num_questions_failed_validation',
            'difficulty_distribution', 'bloom_taxonomy_distribution', 'default_marks',
            'default_negative_marks', 'language', 'safe_diagnostics', 'error_message',
            'requested_by', 'requested_by_email', 'created_at', 'updated_at'
        ]
        read_only_fields = fields


class GeneratedCandidateRecordSerializer(serializers.ModelSerializer):
    persisted_question_id = serializers.UUIDField(source='persisted_question.id', read_only=True)

    class Meta:
        model = GeneratedCandidateRecord
        fields = [
            'id', 'job', 'persisted_question_id', 'candidate_number',
            'question_type', 'status', 'candidate_data', 'validation_errors',
            'provenance_info', 'created_at'
        ]
        read_only_fields = fields
