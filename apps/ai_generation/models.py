import uuid
from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from apps.accounts.models import Institute, User
from apps.academics.models import Subject, Unit, Topic, LearningOutcome
from apps.questions.models import Question, QuestionType, DifficultyLevel, BloomTaxonomy


class DocumentProcessingStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PROCESSING = 'processing', 'Processing'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'


class DocumentType(models.TextChoices):
    PDF = 'pdf', 'PDF Document'
    DOCX = 'docx', 'Word Document'
    TXT = 'txt', 'Plain Text File'


class GenerationJobStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PROCESSING = 'processing', 'Processing'
    COMPLETED = 'completed', 'Completed'
    PARTIALLY_COMPLETED = 'partially_completed', 'Partially Completed'
    FAILED = 'failed', 'Failed'


class CandidateStatus(models.TextChoices):
    SAVED = 'saved', 'Saved as Draft Question'
    VALIDATION_FAILED = 'validation_failed', 'Validation Failed'
    UNSUPPORTED_CONTENT = 'unsupported_content', 'Unsupported by Source Material'


class SourceDocument(models.Model):
    """
    Authorized academic source material uploaded by teachers or administrators.
    Maintains institute boundary, associated curriculum scope, and extracted text.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='source_documents')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='source_documents')
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name='source_documents')
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name='source_documents')

    title = models.CharField(max_length=255)
    file = models.FileField(upload_to='source_materials/%Y/%m/', max_length=500)
    file_type = models.CharField(max_length=20, choices=DocumentType.choices)
    file_size = models.PositiveIntegerField(default=0, help_text="File size in bytes")
    processing_status = models.CharField(
        max_length=30,
        choices=DocumentProcessingStatus.choices,
        default=DocumentProcessingStatus.PENDING,
        db_index=True
    )
    error_message = models.TextField(blank=True, default='')
    extracted_text = models.TextField(blank=True, default='')
    total_pages = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_source_documents'
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_source_document'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['institute', 'subject', 'processing_status']),
        ]
        verbose_name = 'Source Document'
        verbose_name_plural = 'Source Documents'

    def clean(self):
        if self.subject_id and self.subject.institute_id != self.institute_id:
            raise ValidationError({'subject': 'Subject must belong to the document’s institute.'})
        if self.unit_id and self.unit.subject_id != self.subject_id:
            raise ValidationError({'unit': 'Unit must belong to the selected subject.'})
        if self.topic_id and self.topic.unit_id != self.unit_id:
            raise ValidationError({'topic': 'Topic must belong to the selected unit.'})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.subject.code} - {self.institute.code})"


class SourceDocumentChunk(models.Model):
    """
    Text passage chunk extracted from source document. Preserves page and section provenance.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name='chunks')
    chunk_index = models.PositiveIntegerField()
    section_title = models.CharField(max_length=255, blank=True, default='')
    page_number = models.PositiveIntegerField(null=True, blank=True)
    content = models.TextField()
    char_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_source_document_chunk'
        unique_together = ('document', 'chunk_index')
        ordering = ['chunk_index']
        verbose_name = 'Source Document Chunk'
        verbose_name_plural = 'Source Document Chunks'

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document.title} (Page {self.page_number or 'N/A'})"


class QuestionGenerationJob(models.Model):
    """
    Audit and tracking entity for an AI question generation operation.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='question_generation_jobs')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='question_generation_jobs')
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name='question_generation_jobs')
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name='question_generation_jobs')
    learning_outcome = models.ForeignKey(
        LearningOutcome,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='question_generation_jobs'
    )
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='question_generation_jobs'
    )
    source_documents = models.ManyToManyField(SourceDocument, related_name='generation_jobs', blank=True)
    status = models.CharField(
        max_length=30,
        choices=GenerationJobStatus.choices,
        default=GenerationJobStatus.PENDING,
        db_index=True
    )
    question_types = models.JSONField(default=list, help_text="e.g. ['mcq', 'short_answer']")
    num_questions_requested = models.PositiveIntegerField(default=5)
    num_questions_generated = models.PositiveIntegerField(default=0)
    num_questions_failed_validation = models.PositiveIntegerField(default=0)
    difficulty_distribution = models.JSONField(default=dict, blank=True, help_text="e.g. {'easy': 2, 'medium': 3}")
    bloom_taxonomy_distribution = models.JSONField(default=dict, blank=True, help_text="e.g. {'understand': 2, 'apply': 3}")
    default_marks = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    default_negative_marks = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    language = models.CharField(max_length=50, default='English')
    safe_diagnostics = models.JSONField(default=dict, blank=True, help_text="Model name, latency ms, token estimates")
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_question_generation_job'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['institute', 'status', 'created_at']),
        ]
        verbose_name = 'Question Generation Job'
        verbose_name_plural = 'Question Generation Jobs'

    def clean(self):
        if self.subject_id and self.subject.institute_id != self.institute_id:
            raise ValidationError({'subject': 'Subject must belong to the job’s institute.'})
        if self.unit_id and self.unit.subject_id != self.subject_id:
            raise ValidationError({'unit': 'Unit must belong to the selected subject.'})
        if self.topic_id and self.topic.unit_id != self.unit_id:
            raise ValidationError({'topic': 'Topic must belong to the selected unit.'})
        if self.learning_outcome_id and self.learning_outcome.subject_id != self.subject_id:
            raise ValidationError({'learning_outcome': 'Learning outcome must belong to the selected subject.'})
        if self.num_questions_requested > 20:
            raise ValidationError({'num_questions_requested': 'Maximum 20 questions can be requested per generation job.'})
        if self.num_questions_requested < 1:
            raise ValidationError({'num_questions_requested': 'Must request at least 1 question.'})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Job {self.id} [{self.subject.code}] - {self.status}"


class GeneratedCandidateRecord(models.Model):
    """
    Diagnostics and outcome log for each candidate question produced by the model.
    Tracks whether the candidate was successfully persisted into M3 Question Bank or failed validation.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(QuestionGenerationJob, on_delete=models.CASCADE, related_name='candidates')
    persisted_question = models.ForeignKey(
        Question,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_candidate_records'
    )
    candidate_number = models.PositiveIntegerField(default=1)
    question_type = models.CharField(max_length=30)
    status = models.CharField(
        max_length=30,
        choices=CandidateStatus.choices,
        default=CandidateStatus.SAVED
    )
    candidate_data = models.JSONField(default=dict)
    validation_errors = models.JSONField(default=dict, blank=True)
    provenance_info = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_generated_candidate_record'
        ordering = ['candidate_number']
        verbose_name = 'Generated Candidate Record'
        verbose_name_plural = 'Generated Candidate Records'

    def __str__(self):
        return f"Job {self.job_id} Candidate #{self.candidate_number} ({self.status})"
