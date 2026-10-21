from decimal import Decimal
from django.db import transaction
from rest_framework import serializers
from apps.accounts.models import Institute
from apps.academics.models import Subject, Unit, Topic, LearningOutcome
from .models import (
    Question,
    QuestionOption,
    AnswerKey,
    QuestionRubric,
    QuestionSourceReference,
    QuestionVersion,
    QuestionTag,
    QuestionReview,
    QuestionType,
    QuestionStatus,
)


class QuestionTagSerializer(serializers.ModelSerializer):
    institute_code = serializers.CharField(source='institute.code', read_only=True)

    class Meta:
        model = QuestionTag
        fields = ['id', 'institute', 'institute_code', 'name', 'slug', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']


class QuestionOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionOption
        fields = ['id', 'option_key', 'option_text', 'is_correct', 'explanation', 'order']
        read_only_fields = ['id']


class AnswerKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerKey
        fields = ['id', 'expected_answer', 'sample_solution', 'test_cases', 'explanation', 'keywords', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class QuestionRubricSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionRubric
        fields = ['id', 'criterion', 'description', 'max_marks', 'order', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class QuestionSourceReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionSourceReference
        fields = ['id', 'source_title', 'page_or_section', 'excerpt', 'relevance_note', 'created_at']
        read_only_fields = ['id', 'created_at']


class QuestionVersionSerializer(serializers.ModelSerializer):
    changed_by_email = serializers.CharField(source='changed_by.email', read_only=True)

    class Meta:
        model = QuestionVersion
        fields = ['id', 'version_number', 'snapshot_data', 'changed_by', 'changed_by_email', 'change_reason', 'created_at']
        read_only_fields = ['id', 'created_at']


class QuestionReviewSerializer(serializers.ModelSerializer):
    reviewer_email = serializers.CharField(source='reviewer.email', read_only=True)

    class Meta:
        model = QuestionReview
        fields = ['id', 'question', 'reviewer', 'reviewer_email', 'decision', 'comment', 'created_at']
        read_only_fields = ['id', 'created_at']


class QuestionSerializer(serializers.ModelSerializer):
    """
    Detailed read serializer including all normalized child relations.
    """
    options = QuestionOptionSerializer(many=True, read_only=True)
    answer_key = AnswerKeySerializer(read_only=True)
    rubrics = QuestionRubricSerializer(many=True, read_only=True)
    source_references = QuestionSourceReferenceSerializer(many=True, read_only=True)
    tags = QuestionTagSerializer(many=True, read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    institute_code = serializers.CharField(source='institute.code', read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True)

    class Meta:
        model = Question
        fields = [
            'id', 'institute', 'institute_code', 'subject', 'subject_code', 'subject_name',
            'unit', 'topic', 'learning_outcome', 'question_type', 'question_text',
            'difficulty', 'marks', 'negative_marks', 'bloom_taxonomy', 'origin_type',
            'status', 'current_version', 'created_by', 'created_by_email', 'tags',
            'code_metadata', 'options', 'answer_key', 'rubrics', 'source_references',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'current_version', 'created_by', 'created_at', 'updated_at']


class QuestionCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer with strict question-type validation,
    options handling, answer key creation, and safe version snapshots.
    """
    options = QuestionOptionSerializer(many=True, required=False)
    answer_key = AnswerKeySerializer(required=False, allow_null=True)
    rubrics = QuestionRubricSerializer(many=True, required=False)
    source_references = QuestionSourceReferenceSerializer(many=True, required=False)
    tag_ids = serializers.PrimaryKeyRelatedField(
        queryset=QuestionTag.objects.all(),
        many=True,
        required=False,
        write_only=True
    )
    change_reason = serializers.CharField(required=False, write_only=True, default='')

    class Meta:
        model = Question
        fields = [
            'id', 'institute', 'subject', 'unit', 'topic', 'learning_outcome',
            'question_type', 'question_text', 'difficulty', 'marks', 'negative_marks',
            'bloom_taxonomy', 'origin_type', 'status', 'code_metadata', 'options',
            'answer_key', 'rubrics', 'source_references', 'tag_ids', 'change_reason'
        ]
        read_only_fields = ['id', 'status']

    def validate(self, attrs):
        if 'status' in self.initial_data:
            raise serializers.ValidationError({
                'status': 'Question status can only be changed through the question review workflow.'
            })
        inst = attrs.get('institute') or (self.instance.institute if self.instance else None)
        subj = attrs.get('subject') or (self.instance.subject if self.instance else None)
        unit = attrs.get('unit') or (self.instance.unit if self.instance else None)
        topic = attrs.get('topic') or (self.instance.topic if self.instance else None)
        lo = attrs.get('learning_outcome') or (self.instance.learning_outcome if self.instance else None)
        q_type = attrs.get('question_type') or (self.instance.question_type if self.instance else QuestionType.MCQ)
        marks = attrs.get('marks', self.instance.marks if self.instance else Decimal('1.00'))
        neg_marks = attrs.get('negative_marks', self.instance.negative_marks if self.instance else Decimal('0.00'))

        # 1. Marks validation
        if marks <= Decimal('0.00'):
            raise serializers.ValidationError({'marks': 'Question marks must be strictly positive.'})
        if neg_marks < Decimal('0.00'):
            raise serializers.ValidationError({'negative_marks': 'Negative marks cannot be negative.'})
        if neg_marks > marks:
            raise serializers.ValidationError({'negative_marks': 'Negative marks cannot exceed question marks.'})

        # 2. Cross-institute validation
        if subj and inst and subj.institute_id != inst.id:
            raise serializers.ValidationError({'subject': 'Subject must belong to the question’s institute.'})
        if unit and subj and unit.subject_id != subj.id:
            raise serializers.ValidationError({'unit': 'Unit must belong to the selected subject.'})
        if topic and unit and topic.unit_id != unit.id:
            raise serializers.ValidationError({'topic': 'Topic must belong to the selected unit.'})
        if lo and subj and lo.subject_id != subj.id:
            raise serializers.ValidationError({'learning_outcome': 'Learning outcome must belong to the selected subject.'})

        # 3. Status restriction: Do not permit direct setting to 'approved'
        status_val = attrs.get('status')
        if status_val == QuestionStatus.APPROVED:
            raise serializers.ValidationError({
                'status': "Questions cannot be directly created or set as 'approved'. Must follow the review workflow."
            })

        # 4. Question type specific structural validation
        options = attrs.get('options', [])
        answer_key = attrs.get('answer_key')

        if q_type == QuestionType.MCQ:
            if not options and not (self.instance and self.instance.options.exists()):
                raise serializers.ValidationError({'options': 'MCQ questions require at least 2 options.'})
            if options:
                if len(options) < 2:
                    raise serializers.ValidationError({'options': 'MCQ questions require at least 2 options.'})
                has_correct = any(opt.get('is_correct', False) for opt in options)
                if not has_correct:
                    raise serializers.ValidationError({'options': 'At least one MCQ option must be marked as correct.'})

        elif q_type == QuestionType.TRUE_FALSE:
            if not options and not (self.instance and self.instance.options.exists()):
                raise serializers.ValidationError({'options': 'True/False questions require exactly 2 options.'})
            if options:
                if len(options) != 2:
                    raise serializers.ValidationError({'options': 'True/False questions require exactly 2 options (True and False).'})
                correct_count = sum(1 for opt in options if opt.get('is_correct', False))
                if correct_count != 1:
                    raise serializers.ValidationError({'options': 'Exactly one option must be marked as correct for True/False questions.'})

        elif q_type in [QuestionType.SHORT_ANSWER, QuestionType.LONG_ANSWER]:
            has_existing_ak = False
            if self.instance:
                try:
                    has_existing_ak = (self.instance.answer_key is not None)
                except Exception:
                    has_existing_ak = False
            if not answer_key and not has_existing_ak:
                raise serializers.ValidationError({'answer_key': f"Expected answer key is required for {q_type}."})

        elif q_type == QuestionType.CODING:
            code_meta = attrs.get('code_metadata') or (self.instance.code_metadata if self.instance else {})
            if not code_meta or not code_meta.get('language'):
                raise serializers.ValidationError({'code_metadata': "Coding questions require 'language' in code_metadata."})
            if not answer_key or not answer_key.get('test_cases'):
                raise serializers.ValidationError({'answer_key': "Coding questions require test cases in the answer key."})

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        options_data = validated_data.pop('options', [])
        answer_key_data = validated_data.pop('answer_key', None)
        rubrics_data = validated_data.pop('rubrics', [])
        sources_data = validated_data.pop('source_references', [])
        tag_ids = validated_data.pop('tag_ids', [])
        validated_data.pop('change_reason', '')
        validated_data.pop('status', None)

        # Attach creator and default status to draft
        user = self.context['request'].user
        validated_data['created_by'] = user
        validated_data['status'] = QuestionStatus.DRAFT
        validated_data['current_version'] = 1

        question = Question.objects.create(**validated_data)

        if tag_ids:
            question.tags.set(tag_ids)

        for opt in options_data:
            QuestionOption.objects.create(question=question, **opt)

        if answer_key_data:
            AnswerKey.objects.create(question=question, **answer_key_data)

        for rubric in rubrics_data:
            QuestionRubric.objects.create(question=question, **rubric)

        for source in sources_data:
            QuestionSourceReference.objects.create(question=question, **source)

        from apps.audit.services import record_audit_event

        record_audit_event(
            action='question.created',
            resource_type='question',
            resource_id=question.pk,
            actor=user,
            institute=question.institute,
            metadata={'to_status': question.status},
        )
        return question

    @transaction.atomic
    def update(self, instance, validated_data):
        validated_data.pop('status', None)
        change_reason = validated_data.pop('change_reason', 'Question updated')
        options_data = validated_data.pop('options', None)
        answer_key_data = validated_data.pop('answer_key', None)
        rubrics_data = validated_data.pop('rubrics', None)
        sources_data = validated_data.pop('source_references', None)
        tag_ids = validated_data.pop('tag_ids', None)

        user = self.context['request'].user

        # 1. Take immutable historical snapshot of current version BEFORE modifying
        instance.create_version_snapshot(changed_by=user, reason=change_reason)

        # 2. Increment version number
        instance.current_version += 1

        # 3. Update main fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # 4. Update child relations if provided
        if options_data is not None:
            instance.options.all().delete()
            for opt in options_data:
                QuestionOption.objects.create(question=instance, **opt)

        if answer_key_data is not None:
            ak_exists = False
            try:
                ak_exists = (instance.answer_key is not None)
            except Exception:
                ak_exists = False
            if ak_exists:
                for k, v in answer_key_data.items():
                    setattr(instance.answer_key, k, v)
                instance.answer_key.save()
            else:
                AnswerKey.objects.create(question=instance, **answer_key_data)

        if rubrics_data is not None:
            instance.rubrics.all().delete()
            for r in rubrics_data:
                QuestionRubric.objects.create(question=instance, **r)

        if sources_data is not None:
            instance.source_references.all().delete()
            for s in sources_data:
                QuestionSourceReference.objects.create(question=instance, **s)

        if tag_ids is not None:
            instance.tags.set(tag_ids)

        from apps.audit.services import record_audit_event

        record_audit_event(
            action='question.updated',
            resource_type='question',
            resource_id=instance.pk,
            actor=user,
            institute=instance.institute,
        )
        return instance
