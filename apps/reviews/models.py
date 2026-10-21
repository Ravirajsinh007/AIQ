from django.db import models
import uuid
from apps.accounts.models import User, Institute
from apps.questions.models import Question, QuestionStatus


class ReviewDecision(models.TextChoices):
    SUBMIT = 'submit', 'Submitted for Review'
    APPROVE = 'approve', 'Approve'
    REJECT = 'reject', 'Reject'
    REQUEST_REVISION = 'request_revision', 'Request Revision'


class ReviewActionType(models.TextChoices):
    SUBMIT = 'submit', 'Submitted for Review'
    APPROVE = 'approve', 'Approved'
    REJECT = 'reject', 'Rejected'
    REQUEST_REVISION = 'request_revision', 'Revision Requested'
    RESUBMIT = 'resubmit', 'Resubmitted for Review'
    ARCHIVE = 'archive', 'Archived'
    RESTORE_DRAFT = 'restore_draft', 'Restored to Draft'


class QuestionReviewRecord(models.Model):
    """
    Formal M5 verification & review decision audit log.
    Tracks every action taken on a question during its review lifecycle.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='verification_reviews')
    reviewer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='question_verification_reviews'
    )
    decision = models.CharField(max_length=30, choices=ReviewDecision.choices)
    from_status = models.CharField(max_length=30, choices=QuestionStatus.choices)
    to_status = models.CharField(max_length=30, choices=QuestionStatus.choices)
    rejection_reason = models.TextField(blank=True, default='')
    revision_feedback = models.TextField(blank=True, default='')
    general_notes = models.TextField(blank=True, default='')
    rubric_scores = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional scoring rubric feedback e.g. {'scientific_accuracy': 5, 'clarity': 4}"
    )
    question_version = models.PositiveIntegerField(
        help_text="The snapshot version of the question when this review action was performed"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'reviews_question_review_record'
        ordering = ['-created_at']
        verbose_name = 'Question Review Record'
        verbose_name_plural = 'Question Review Records'
        indexes = [
            models.Index(fields=['question', '-created_at']),
            models.Index(fields=['reviewer', '-created_at']),
            models.Index(fields=['decision', '-created_at']),
        ]

    def __str__(self):
        return f"Review for Q {self.question_id}: {self.decision} ({self.from_status} -> {self.to_status})"
