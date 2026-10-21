import uuid
from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from apps.accounts.models import Institute, User, UserInstituteMembership, RoleChoices
from apps.academics.models import Subject, Unit, Topic, LearningOutcome


class QuestionType(models.TextChoices):
    MCQ = 'mcq', 'Multiple Choice Question'
    TRUE_FALSE = 'true_false', 'True / False'
    SHORT_ANSWER = 'short_answer', 'Short Answer'
    LONG_ANSWER = 'long_answer', 'Long Answer'
    CODING = 'coding', 'Coding Question'


class DifficultyLevel(models.TextChoices):
    EASY = 'easy', 'Easy'
    MEDIUM = 'medium', 'Medium'
    HARD = 'hard', 'Hard'


class BloomTaxonomy(models.TextChoices):
    REMEMBER = 'remember', 'Remember / Knowledge'
    UNDERSTAND = 'understand', 'Understand / Comprehension'
    APPLY = 'apply', 'Apply / Application'
    ANALYZE = 'analyze', 'Analyze / Analysis'
    EVALUATE = 'evaluate', 'Evaluate / Evaluation'
    CREATE = 'create', 'Create / Synthesis'


class QuestionOrigin(models.TextChoices):
    MANUAL = 'manual', 'Manual Entry'
    AI_GENERATED = 'ai_generated', 'AI Generated'


class QuestionStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    UNDER_REVIEW = 'under_review', 'Under Review'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'
    ARCHIVED = 'archived', 'Archived'


class QuestionTag(models.Model):
    """
    Categorization tags for questions scoped to an institute.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='question_tags')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'questions_question_tag'
        unique_together = ('institute', 'name')
        ordering = ['name']
        verbose_name = 'Question Tag'
        verbose_name_plural = 'Question Tags'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.institute.code})"


class Question(models.Model):
    """
    Central Question Bank Entity.
    Stores questions of all supported types, academic associations,
    Bloom's levels, marks, difficulty, origin, and review status.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='questions')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='questions')
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name='questions')
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name='questions')
    learning_outcome = models.ForeignKey(
        LearningOutcome,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='questions'
    )

    question_type = models.CharField(
        max_length=30,
        choices=QuestionType.choices,
        default=QuestionType.MCQ,
        db_index=True
    )
    question_text = models.TextField()
    difficulty = models.CharField(
        max_length=20,
        choices=DifficultyLevel.choices,
        default=DifficultyLevel.MEDIUM,
        db_index=True
    )
    marks = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    negative_marks = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    bloom_taxonomy = models.CharField(
        max_length=30,
        choices=BloomTaxonomy.choices,
        default=BloomTaxonomy.UNDERSTAND,
        db_index=True
    )
    origin_type = models.CharField(
        max_length=20,
        choices=QuestionOrigin.choices,
        default=QuestionOrigin.MANUAL
    )
    status = models.CharField(
        max_length=20,
        choices=QuestionStatus.choices,
        default=QuestionStatus.DRAFT,
        db_index=True
    )
    current_version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_questions'
    )
    tags = models.ManyToManyField(QuestionTag, blank=True, related_name='questions')
    code_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="For coding questions: programming languages, starter template, execution constraints"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'questions_question'
        ordering = ['-created_at']
        verbose_name = 'Question'
        verbose_name_plural = 'Questions'
        indexes = [
            models.Index(fields=['institute', 'status']),
            models.Index(fields=['subject', 'question_type', 'difficulty']),
            models.Index(fields=['subject', 'status']),
        ]

    def clean(self):
        # 1. Marks validation
        if self.marks <= Decimal('0.00'):
            raise ValidationError({'marks': 'Question marks must be strictly positive.'})
        if self.negative_marks < Decimal('0.00'):
            raise ValidationError({'negative_marks': 'Negative marks cannot be less than zero.'})
        if self.negative_marks > self.marks:
            raise ValidationError({'negative_marks': 'Negative marks cannot exceed positive marks.'})

        # 2. Cross-institute checks
        if self.subject_id and self.subject.institute_id != self.institute_id:
            raise ValidationError({'subject': 'Subject must belong to the question’s institute.'})
        if self.unit_id and self.unit.subject_id != self.subject_id:
            raise ValidationError({'unit': 'Unit must belong to the selected subject.'})
        if self.topic_id and self.topic.unit_id != self.unit_id:
            raise ValidationError({'topic': 'Topic must belong to the selected unit.'})
        if self.learning_outcome_id and self.learning_outcome.subject_id != self.subject_id:
            raise ValidationError({'learning_outcome': 'Learning outcome must belong to the selected subject.'})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def create_version_snapshot(self, changed_by=None, reason=''):
        """
        Creates an immutable historical snapshot of the current question state.
        """
        options_data = [
            {
                'key': opt.option_key,
                'text': opt.option_text,
                'is_correct': opt.is_correct,
                'explanation': opt.explanation,
                'order': opt.order
            }
            for opt in self.options.all().order_by('order')
        ]
        answer_key_data = None
        try:
            ak = self.answer_key
            if ak:
                answer_key_data = {
                    'expected_answer': ak.expected_answer,
                    'sample_solution': ak.sample_solution,
                    'test_cases': ak.test_cases,
                    'explanation': ak.explanation,
                    'keywords': ak.keywords
                }
        except Exception:
            answer_key_data = None
        rubrics_data = [
            {
                'criterion': r.criterion,
                'description': r.description,
                'max_marks': str(r.max_marks),
                'order': r.order
            }
            for r in self.rubrics.all().order_by('order')
        ]

        snapshot = {
            'question_text': self.question_text,
            'question_type': self.question_type,
            'difficulty': self.difficulty,
            'marks': str(self.marks),
            'negative_marks': str(self.negative_marks),
            'bloom_taxonomy': self.bloom_taxonomy,
            'status': self.status,
            'code_metadata': self.code_metadata,
            'options': options_data,
            'answer_key': answer_key_data,
            'rubrics': rubrics_data,
        }

        QuestionVersion.objects.create(
            question=self,
            version_number=self.current_version,
            snapshot_data=snapshot,
            changed_by=changed_by,
            change_reason=reason
        )

    def __str__(self):
        return f"[{self.subject.code}] {self.question_type.upper()} ({self.marks}M): {self.question_text[:50]}"


class QuestionOption(models.Model):
    """
    Normalized options for Multiple Choice and True/False questions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    option_key = models.CharField(max_length=10)  # e.g., 'A', 'B', 'C', 'D'
    option_text = models.TextField()
    is_correct = models.BooleanField(default=False)
    explanation = models.TextField(blank=True, default='')
    order = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = 'questions_question_option'
        unique_together = ('question', 'option_key')
        ordering = ['order', 'option_key']
        verbose_name = 'Question Option'
        verbose_name_plural = 'Question Options'

    def __str__(self):
        return f"{self.option_key}: {self.option_text[:40]}"


class AnswerKey(models.Model):
    """
    Expected answer, sample solution, or automated test cases for coding questions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.OneToOneField(Question, on_delete=models.CASCADE, related_name='answer_key')
    expected_answer = models.TextField(help_text="Expected answer or canonical answer formula")
    sample_solution = models.TextField(blank=True, default='', help_text="Detailed worked solution")
    test_cases = models.JSONField(
        default=list,
        blank=True,
        help_text="For coding questions: [{'input': '...', 'expected_output': '...', 'is_hidden': false}]"
    )
    explanation = models.TextField(blank=True, default='')
    keywords = models.JSONField(default=list, blank=True, help_text="Key phrases or terms for grading")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'questions_answer_key'
        verbose_name = 'Answer Key'
        verbose_name_plural = 'Answer Keys'

    def __str__(self):
        return f"AnswerKey for {self.question_id}"


class QuestionRubric(models.Model):
    """
    Marking rubric criteria for subjective questions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='rubrics')
    criterion = models.CharField(max_length=255)
    description = models.TextField()
    max_marks = models.DecimalField(max_digits=5, decimal_places=2)
    order = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'questions_question_rubric'
        ordering = ['order']
        verbose_name = 'Question Rubric'
        verbose_name_plural = 'Question Rubrics'

    def __str__(self):
        return f"{self.criterion} ({self.max_marks}M)"


class QuestionSourceReference(models.Model):
    """
    Provenance tracking connecting questions to source material, textbooks,
    or teacher-uploaded syllabus documents.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='source_references')
    source_title = models.CharField(max_length=255, help_text="Title of textbook, paper, or syllabus material")
    page_or_section = models.CharField(max_length=100, blank=True, default='')
    excerpt = models.TextField(help_text="Quoted text or evidence passage from authorized source material")
    relevance_note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'questions_question_source_reference'
        ordering = ['-created_at']
        verbose_name = 'Question Source Reference'
        verbose_name_plural = 'Question Source References'

    def __str__(self):
        return f"{self.source_title} ({self.page_or_section})"


class QuestionVersion(models.Model):
    """
    Immutable revision history snapshot.
    Preserves historical content whenever a question is updated.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField()
    snapshot_data = models.JSONField(help_text="Immutable JSON snapshot of question state at this version")
    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_question_versions'
    )
    change_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'questions_question_version'
        unique_together = ('question', 'version_number')
        ordering = ['-version_number']
        verbose_name = 'Question Version'
        verbose_name_plural = 'Question Versions'

    def __str__(self):
        return f"Q {self.question_id} v{self.version_number}"


class QuestionReview(models.Model):
    """
    Records reviewer decisions, feedback, and timestamps.
    Integration point for M5 verification.
    """
    DECISION_APPROVED = 'approved'
    DECISION_REJECTED = 'rejected'
    DECISION_NEEDS_REVISION = 'needs_revision'
    DECISION_CHOICES = [
        (DECISION_APPROVED, 'Approved'),
        (DECISION_REJECTED, 'Rejected'),
        (DECISION_NEEDS_REVISION, 'Needs Revision'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='performed_question_reviews'
    )
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES)
    comment = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'questions_question_review'
        ordering = ['-created_at']
        verbose_name = 'Question Review'
        verbose_name_plural = 'Question Reviews'

    def __str__(self):
        return f"Review for {self.question_id}: {self.decision}"
