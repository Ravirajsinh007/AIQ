import uuid
from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Institute, User
from apps.academics.models import (
    Department,
    Program,
    AcademicYear,
    Semester,
    Subject,
    Unit,
    Topic,
    LearningOutcome,
)
from apps.questions.models import (
    Question,
    QuestionType,
    DifficultyLevel,
    BloomTaxonomy,
)


class BlueprintStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    ACTIVE = 'active', _('Active')
    ARCHIVED = 'archived', _('Archived')


class GeneratedPaperStatus(models.TextChoices):
    GENERATING = 'generating', _('Generating')
    COMPLETED = 'completed', _('Completed')
    FAILED = 'failed', _('Failed')


class PaperWorkflowStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    SUBMITTED = 'submitted', _('Submitted for Review')
    APPROVED = 'approved', _('Approved')
    REJECTED = 'rejected', _('Rejected')
    SCHEDULED = 'scheduled', _('Scheduled for Release')
    RELEASED = 'released', _('Released')
    ARCHIVED = 'archived', _('Archived')


class PaperBlueprint(models.Model):
    """
    Examination Blueprint model specifying paper structure, mark distributions,
    duration, sections, and selection rules.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='blueprints')
    title = models.CharField(max_length=255)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='blueprints')
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.SET_NULL, null=True, blank=True, related_name='blueprints')
    semester = models.ForeignKey(Semester, on_delete=models.SET_NULL, null=True, blank=True, related_name='blueprints')
    program = models.ForeignKey(Program, on_delete=models.SET_NULL, null=True, blank=True, related_name='blueprints')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='blueprints')

    total_marks = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('100.00'))
    duration_minutes = models.PositiveIntegerField(default=180, help_text="Examination duration in minutes")
    status = models.CharField(max_length=20, choices=BlueprintStatus.choices, default=BlueprintStatus.DRAFT, db_index=True)
    allow_question_reuse = models.BooleanField(
        default=False,
        help_text="If False, prevent duplicate question selection within the same paper."
    )
    general_instructions = models.TextField(blank=True, default='')

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_blueprints'
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'blueprints_paper_blueprint'
        ordering = ['-created_at']
        verbose_name = 'Paper Blueprint'
        verbose_name_plural = 'Paper Blueprints'
        indexes = [
            models.Index(fields=['institute', 'status']),
            models.Index(fields=['subject', 'status']),
        ]

    def __str__(self):
        return f"{self.title} - {self.subject.code} ({self.total_marks} Marks)"

    def clean(self):
        if self.subject_id and self.institute_id != self.subject.institute_id:
            raise ValidationError({'subject': 'Subject must belong to the blueprint’s institute.'})
        if self.department_id and self.institute_id != self.department.institute_id:
            raise ValidationError({'department': 'Department must belong to the blueprint’s institute.'})
        if self.program_id and self.institute_id != self.program.institute_id:
            raise ValidationError({'program': 'Program must belong to the blueprint’s institute.'})
        if self.total_marks <= Decimal('0.00'):
            raise ValidationError({'total_marks': 'Total marks must be strictly greater than 0.'})
        if self.duration_minutes <= 0:
            raise ValidationError({'duration_minutes': 'Duration must be greater than 0.'})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class BlueprintSection(models.Model):
    """
    Named section of a blueprint (e.g. Section A: Multiple Choice Questions,
    Section B: Descriptive Problems).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blueprint = models.ForeignKey(PaperBlueprint, on_delete=models.CASCADE, related_name='sections')
    name = models.CharField(max_length=100, help_text="e.g. Section A, Part 1")
    order = models.PositiveIntegerField(default=1)
    instructions = models.TextField(blank=True, default='')
    target_marks = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'blueprints_blueprint_section'
        ordering = ['blueprint', 'order']
        unique_together = ('blueprint', 'name')
        verbose_name = 'Blueprint Section'
        verbose_name_plural = 'Blueprint Sections'

    def __str__(self):
        return f"{self.blueprint.title} - {self.name} ({self.target_marks} Marks)"

    def clean(self):
        if self.target_marks <= Decimal('0.00'):
            raise ValidationError({'target_marks': 'Section target marks must be strictly greater than 0.'})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class BlueprintRule(models.Model):
    """
    Normalized selection rule specifying criteria for a question group within a section.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.ForeignKey(BlueprintSection, on_delete=models.CASCADE, related_name='rules')
    order = models.PositiveIntegerField(default=1)
    
    question_type = models.CharField(
        max_length=30,
        choices=QuestionType.choices,
        help_text="Required question type"
    )
    question_count = models.PositiveIntegerField(
        help_text="Exact number of questions required by this rule"
    )
    marks_per_question = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Marks allocated to each question selected by this rule"
    )
    
    # Optional Academic Scope filters
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name='blueprint_rules')
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name='blueprint_rules')
    learning_outcome = models.ForeignKey(LearningOutcome, on_delete=models.SET_NULL, null=True, blank=True, related_name='blueprint_rules')

    # Distribution constraints (optional exact match or distribution breakdown)
    difficulty = models.CharField(
        max_length=20,
        choices=DifficultyLevel.choices,
        null=True,
        blank=True,
        help_text="Optional exact difficulty required"
    )
    bloom_taxonomy = models.CharField(
        max_length=30,
        choices=BloomTaxonomy.choices,
        null=True,
        blank=True,
        help_text="Optional exact Bloom taxonomy level required"
    )
    difficulty_distribution = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional count or percentage distribution e.g. {'easy': 2, 'medium': 3}"
    )
    bloom_taxonomy_distribution = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional distribution e.g. {'understand': 2, 'apply': 3}"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'blueprints_blueprint_rule'
        ordering = ['section', 'order']
        verbose_name = 'Blueprint Rule'
        verbose_name_plural = 'Blueprint Rules'

    def __str__(self):
        return f"{self.section.name} Rule #{self.order}: {self.question_count}x {self.question_type} @ {self.marks_per_question}M"

    @property
    def total_rule_marks(self):
        return Decimal(str(self.question_count)) * self.marks_per_question

    def clean(self):
        if self.question_count <= 0:
            raise ValidationError({'question_count': 'Question count must be greater than 0.'})
        if self.marks_per_question <= Decimal('0.00'):
            raise ValidationError({'marks_per_question': 'Marks per question must be greater than 0.'})
        
        # Verify academic unit/topic/outcome belongs to blueprint's subject
        blueprint_subject = self.section.blueprint.subject_id
        if self.unit_id and self.unit.subject_id != blueprint_subject:
            raise ValidationError({'unit': 'Selected Unit must belong to the blueprint’s subject.'})
        if self.learning_outcome_id and self.learning_outcome.subject_id != blueprint_subject:
            raise ValidationError({'learning_outcome': 'Selected Learning Outcome must belong to the blueprint’s subject.'})
        if self.topic_id and self.unit_id and self.topic.unit_id != self.unit_id:
            raise ValidationError({'topic': 'Selected Topic must belong to the selected Unit.'})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class GeneratedPaper(models.Model):
    """
    Generated Examination Paper resulting from executing a blueprint against
    the pool of approved questions in M3.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='generated_papers')
    blueprint = models.ForeignKey(PaperBlueprint, on_delete=models.PROTECT, related_name='generated_papers')
    title = models.CharField(max_length=255)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='generated_papers')
    
    total_marks = models.DecimalField(max_digits=6, decimal_places=2)
    duration_minutes = models.PositiveIntegerField(default=180)
    status = models.CharField(
        max_length=20,
        choices=GeneratedPaperStatus.choices,
        default=GeneratedPaperStatus.GENERATING,
        db_index=True
    )
    workflow_status = models.CharField(
        max_length=20,
        choices=PaperWorkflowStatus.choices,
        default=PaperWorkflowStatus.DRAFT,
        db_index=True,
    )
    generation_version = models.PositiveIntegerField(
        default=1,
        help_text="Sequential version number for regenerating papers from the same blueprint."
    )
    blueprint_snapshot = models.JSONField(
        default=dict,
        help_text="Immutable snapshot of the blueprint, sections, and rules at the time of generation."
    )
    validation_report = models.JSONField(
        default=dict,
        blank=True,
        help_text="Detailed outcome summary, question counts, mark checks, and shortage logs."
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_papers'
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_generated_papers',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')
    scheduled_release_at = models.DateTimeField(null=True, blank=True, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='amendments',
    )
    amendment_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'blueprints_generated_paper'
        ordering = ['-created_at']
        verbose_name = 'Generated Paper'
        verbose_name_plural = 'Generated Papers'
        indexes = [
            models.Index(fields=['institute', 'status']),
            models.Index(fields=['institute', 'workflow_status']),
            models.Index(fields=['blueprint', '-generation_version']),
            models.Index(fields=['subject', '-created_at']),
        ]

    def __str__(self):
        return f"{self.title} (v{self.generation_version}) - {self.total_marks} Marks [{self.status}]"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values(
                'institute_id', 'blueprint_id', 'title', 'subject_id', 'total_marks',
                'duration_minutes', 'status', 'generation_version', 'blueprint_snapshot',
                'validation_report', 'created_by_id', 'supersedes_id', 'amendment_reason',
            ).first()
            if original:
                changed = any(
                    original[field] != getattr(self, field)
                    for field in (
                        'institute_id', 'blueprint_id', 'title', 'subject_id', 'total_marks',
                        'duration_minutes', 'status', 'generation_version', 'blueprint_snapshot',
                        'validation_report', 'created_by_id', 'supersedes_id', 'amendment_reason',
                    )
                )
                if changed:
                    raise ValidationError('Generated paper versions are immutable; create an amendment instead.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Generated paper versions are retained; archive them instead of deleting.')


class GeneratedPaperQuestion(models.Model):
    """
    Ordered snapshot of each selected approved question placed into a generated paper.
    Captures immutable question text, options, rubrics, and source citations to preserve
    paper integrity if the source question in M3 is subsequently edited.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    paper = models.ForeignKey(GeneratedPaper, on_delete=models.CASCADE, related_name='paper_questions')
    section_name = models.CharField(max_length=100)
    section_order = models.PositiveIntegerField(default=1)
    question_number = models.PositiveIntegerField(help_text="1, 2, 3... sequential across paper or section")
    
    question = models.ForeignKey(
        Question,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='placed_in_papers'
    )
    question_version = models.PositiveIntegerField(
        help_text="The snapshot version of the question when generated"
    )
    
    question_type = models.CharField(max_length=30, choices=QuestionType.choices)
    question_text = models.TextField()
    marks = models.DecimalField(max_digits=5, decimal_places=2)
    negative_marks = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    difficulty = models.CharField(max_length=20, choices=DifficultyLevel.choices)
    bloom_taxonomy = models.CharField(max_length=30, choices=BloomTaxonomy.choices)

    # Immutable question child content snapshots
    options_snapshot = models.JSONField(
        default=list,
        blank=True,
        help_text="List of normalized options: [{'option_key': 'A', 'option_text': '...'}]"
    )
    rubric_snapshot = models.JSONField(
        default=list,
        blank=True,
        help_text="Grading criteria for subjective questions"
    )
    test_cases_snapshot = models.JSONField(
        default=list,
        blank=True,
        help_text="Immutable coding test cases; hidden cases are never delivered to students."
    )
    code_metadata_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Immutable coding language, starter template, and execution constraints."
    )
    provenance_snapshot = models.JSONField(
        default=list,
        blank=True,
        help_text="Source references and citations"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'blueprints_generated_paper_question'
        ordering = ['section_order', 'question_number']
        unique_together = ('paper', 'question_number')
        verbose_name = 'Generated Paper Question'
        verbose_name_plural = 'Generated Paper Questions'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Generated paper question snapshots are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Generated paper question snapshots cannot be deleted.')

    def __str__(self):
        return f"{self.paper.title} - Q#{self.question_number} ({self.marks}M)"
