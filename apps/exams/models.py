import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.accounts.models import Institute, User
from apps.academics.models import (
    Batch,
    ProgramSemesterSubject,
    Section,
    StudentAcademicPlacement,
)
from apps.blueprints.models import GeneratedPaper, PaperWorkflowStatus
from .storage import PrivateFileSystemStorage


class ExamScheduleStatus(models.TextChoices):
    SCHEDULED = 'scheduled', 'Scheduled'
    CANCELLED = 'cancelled', 'Cancelled'


class ExamAvailabilityState(models.TextChoices):
    SCHEDULED = 'scheduled', 'Scheduled'
    AVAILABLE = 'available', 'Available'
    EXPIRED = 'expired', 'Expired'
    CANCELLED = 'cancelled', 'Cancelled'


class ExamAttemptStatus(models.TextChoices):
    IN_PROGRESS = 'in_progress', 'In Progress'
    SUBMITTED = 'submitted', 'Submitted'
    AUTO_SUBMITTED = 'auto_submitted', 'Auto Submitted'
    EXPIRED = 'expired', 'Expired'
    CANCELLED = 'cancelled', 'Cancelled'


class ExamActivityType(models.TextChoices):
    SCHEDULE_CREATED = 'schedule_created', 'Schedule Created'
    SCHEDULE_UPDATED = 'schedule_updated', 'Schedule Updated'
    SCHEDULE_DELETED = 'schedule_deleted', 'Schedule Deleted'
    SCHEDULE_PUBLISHED = 'schedule_published', 'Schedule Published'
    SCHEDULE_CANCELLED = 'schedule_cancelled', 'Schedule Cancelled'
    ATTEMPT_STARTED = 'attempt_started', 'Attempt Started'
    ATTEMPT_RESUMED = 'attempt_resumed', 'Attempt Resumed'
    ANSWER_SAVED = 'answer_saved', 'Answer Saved'
    ATTEMPT_SUBMITTED = 'attempt_submitted', 'Attempt Submitted'
    ATTEMPT_AUTO_SUBMITTED = 'attempt_auto_submitted', 'Attempt Auto Submitted'
    VISIBILITY_CHANGED = 'visibility_changed', 'Browser Visibility Changed'
    FULLSCREEN_EXIT = 'fullscreen_exit', 'Fullscreen Exit Reported'
    RECONNECT = 'reconnect', 'Reconnect Reported'
    SECURITY_VIOLATION = 'security_violation', 'Security Violation'
    INTEGRITY_FLAG_REVIEWED = 'integrity_flag_reviewed', 'Integrity Flag Reviewed'


class ExamActivitySource(models.TextChoices):
    SERVER_VERIFIED = 'server_verified', 'Server Verified'
    CLIENT_REPORTED = 'client_reported', 'Client Reported'


class IntegrityFlagStatus(models.TextChoices):
    OPEN = 'open', 'Open'
    REVIEWED = 'reviewed', 'Reviewed'
    DISMISSED = 'dismissed', 'Dismissed'


class EvaluationStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    GRADED = 'graded', 'Graded'
    HUMAN_REVIEW = 'human_review', 'Human Review Required'


class CodingSubmissionStatus(models.TextChoices):
    QUEUED = 'queued', 'Queued'
    RUNNING = 'running', 'Running'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'


class HandwrittenSheetStatus(models.TextChoices):
    UPLOADED = 'uploaded', 'Uploaded'
    EXTRACTED = 'extracted', 'Text Extracted'
    HUMAN_REVIEW = 'human_review', 'Human Review Required'
    REVIEWED = 'reviewed', 'Reviewed'
    EXTRACTION_FAILED = 'extraction_failed', 'Extraction Failed'


def handwritten_sheet_upload_path(instance, filename):
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
    return (
        f'answer_sheets/{instance.attempt.exam.institute_id}/'
        f'{instance.attempt_id}/{uuid.uuid4().hex}.{extension}'
    )


class ExamSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='exam_schedules')
    paper = models.ForeignKey(GeneratedPaper, on_delete=models.PROTECT, related_name='exam_schedules')
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name='exam_schedules')
    section = models.ForeignKey(
        Section, on_delete=models.PROTECT, null=True, blank=True, related_name='exam_schedules'
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    revaluation_opens_at = models.DateTimeField(null=True, blank=True)
    revaluation_closes_at = models.DateTimeField(null=True, blank=True)
    instructions = models.TextField(blank=True, default='')
    published = models.BooleanField(default=False, db_index=True)
    status = models.CharField(
        max_length=20, choices=ExamScheduleStatus.choices, default=ExamScheduleStatus.SCHEDULED, db_index=True
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='created_exam_schedules'
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'exams_exam_schedule'
        ordering = ['starts_at', 'created_at']
        indexes = [
            models.Index(fields=['institute', 'status', 'published']),
            models.Index(fields=['batch', 'starts_at', 'ends_at']),
        ]

    def clean(self):
        errors = {}
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            errors['ends_at'] = 'Exam end time must be after the start time.'
        if bool(self.revaluation_opens_at) != bool(self.revaluation_closes_at):
            errors['revaluation_closes_at'] = 'Both revaluation window dates must be set together.'
        if (
            self.revaluation_opens_at and self.revaluation_closes_at
            and self.revaluation_opens_at >= self.revaluation_closes_at
        ):
            errors['revaluation_closes_at'] = 'Revaluation close time must follow its open time.'
        if self.institute_id and self.paper_id and self.paper.institute_id != self.institute_id:
            errors['paper'] = 'Paper must belong to the scheduled institute.'
        if self.paper_id and self.paper.status != 'completed':
            errors['paper'] = 'Only completed generated papers can be scheduled.'
        if self.paper_id and self.paper.workflow_status != PaperWorkflowStatus.RELEASED:
            errors['paper'] = 'Only formally released papers can be scheduled for an exam.'
        if self.institute_id and self.batch_id and self.batch.institute_id != self.institute_id:
            errors['batch'] = 'Batch must belong to the scheduled institute.'
        if self.batch_id and self.section_id and self.section.batch_id != self.batch_id:
            errors['section'] = 'Section must belong to the selected batch.'
        if self.paper_id and self.batch_id:
            blueprint = self.paper.blueprint
            if blueprint.program_id and blueprint.program_id != self.batch.program_id:
                errors['batch'] = 'Batch program must match the paper blueprint program.'
            if blueprint.semester_id and blueprint.semester.program_id != self.batch.program_id:
                errors['batch'] = 'Batch program must match the paper blueprint semester.'
            if blueprint.semester_id and not ProgramSemesterSubject.objects.filter(
                program_id=self.batch.program_id,
                semester_id=blueprint.semester_id,
                subject_id=self.paper.subject_id,
            ).exists():
                errors['batch'] = (
                    'The paper subject must be included in the selected batch program semester.'
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def availability_state(self, at=None):
        at = at or timezone.now()
        if self.status == ExamScheduleStatus.CANCELLED:
            return ExamAvailabilityState.CANCELLED
        if at >= self.ends_at:
            return ExamAvailabilityState.EXPIRED
        if at < self.starts_at:
            return ExamAvailabilityState.SCHEDULED
        return ExamAvailabilityState.AVAILABLE

    def __str__(self):
        return f'{self.paper.title} - {self.batch.name}'


class ExamAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(ExamSchedule, on_delete=models.PROTECT, related_name='attempts')
    placement = models.ForeignKey(
        StudentAcademicPlacement, on_delete=models.PROTECT, related_name='exam_attempts'
    )
    status = models.CharField(
        max_length=20, choices=ExamAttemptStatus.choices, default=ExamAttemptStatus.IN_PROGRESS, db_index=True
    )
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'exams_exam_attempt'
        ordering = ['-started_at']
        constraints = [
            models.UniqueConstraint(
                fields=['exam', 'placement'], name='unique_exam_placement_attempt'
            ),
        ]
        indexes = [
            models.Index(fields=['placement', 'status']),
            models.Index(fields=['exam', 'status']),
        ]

    @property
    def deadline_at(self):
        duration_deadline = self.started_at + timedelta(minutes=self.exam.paper.duration_minutes)
        return min(duration_deadline, self.exam.ends_at)

    def __str__(self):
        return f'{self.placement.student_id} - {self.exam_id} ({self.status})'


class ExamAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name='answers')
    paper_question = models.ForeignKey(
        'blueprints.GeneratedPaperQuestion', on_delete=models.PROTECT, related_name='exam_answers'
    )
    response = models.JSONField()
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'exams_exam_answer'
        constraints = [
            models.UniqueConstraint(fields=['attempt', 'paper_question'], name='unique_attempt_question_answer')
        ]
        indexes = [models.Index(fields=['attempt', 'updated_at'])]


class ExamAnswerEvaluation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    answer = models.OneToOneField(
        ExamAnswer, on_delete=models.CASCADE, related_name='evaluation'
    )
    status = models.CharField(
        max_length=20, choices=EvaluationStatus.choices, default=EvaluationStatus.PENDING, db_index=True
    )
    marks_awarded = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    max_marks = models.DecimalField(max_digits=6, decimal_places=2)
    feedback = models.TextField(blank=True, default='')
    details = models.JSONField(default=dict, blank=True)
    grading_method = models.CharField(max_length=30, blank=True, default='')
    evaluated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='exam_answer_evaluations'
    )
    evaluated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'exams_exam_answer_evaluation'
        indexes = [models.Index(fields=['status', 'updated_at'])]

    def clean(self):
        if self.max_marks <= Decimal('0.00'):
            raise ValidationError({'max_marks': 'Maximum marks must be greater than zero.'})
        if self.marks_awarded is not None:
            minimum = Decimal('0.00')
            if self.grading_method == 'objective':
                minimum = -self.answer.paper_question.negative_marks
            if self.marks_awarded < minimum or self.marks_awarded > self.max_marks:
                raise ValidationError({'marks_awarded': 'Awarded marks are outside the permitted range.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class CodingSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    answer = models.ForeignKey(
        ExamAnswer, on_delete=models.CASCADE, related_name='coding_submissions'
    )
    code = models.TextField()
    language = models.CharField(max_length=50)
    source_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20, choices=CodingSubmissionStatus.choices,
        default=CodingSubmissionStatus.QUEUED, db_index=True
    )
    test_results = models.JSONField(default=list, blank=True)
    passed_count = models.PositiveIntegerField(default=0)
    total_count = models.PositiveIntegerField(default=0)
    marks_awarded = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    error_code = models.CharField(max_length=60, blank=True, default='')
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'exams_coding_submission'
        constraints = [
            models.UniqueConstraint(
                fields=['answer', 'source_hash'], name='unique_answer_coding_source_hash'
            ),
        ]
        indexes = [models.Index(fields=['status', 'submitted_at'])]


class HandwrittenAnswerSheet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.OneToOneField(
        ExamAttempt, on_delete=models.CASCADE, related_name='handwritten_sheet'
    )
    file = models.FileField(
        upload_to=handwritten_sheet_upload_path,
        max_length=500,
        storage=PrivateFileSystemStorage(),
    )
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploaded_handwritten_sheets'
    )
    status = models.CharField(
        max_length=24, choices=HandwrittenSheetStatus.choices,
        default=HandwrittenSheetStatus.UPLOADED, db_index=True
    )
    extracted_text = models.TextField(blank=True, default='')
    extraction_error = models.CharField(max_length=500, blank=True, default='')
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    extracted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'exams_handwritten_answer_sheet'
        indexes = [models.Index(fields=['status', 'uploaded_at'])]


class HandwrittenAnswerEvaluation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sheet = models.ForeignKey(
        HandwrittenAnswerSheet, on_delete=models.CASCADE, related_name='evaluations'
    )
    paper_question = models.ForeignKey(
        'blueprints.GeneratedPaperQuestion', on_delete=models.PROTECT,
        related_name='handwritten_evaluations'
    )
    marks_awarded = models.DecimalField(max_digits=6, decimal_places=2)
    max_marks = models.DecimalField(max_digits=6, decimal_places=2)
    rubric_scores = models.JSONField(default=dict, blank=True)
    feedback = models.TextField(blank=True, default='')
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_handwritten_answers'
    )
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'exams_handwritten_answer_evaluation'
        constraints = [
            models.UniqueConstraint(
                fields=['sheet', 'paper_question'], name='unique_sheet_question_review'
            ),
        ]

    def clean(self):
        if self.marks_awarded < Decimal('0.00') or self.marks_awarded > self.max_marks:
            raise ValidationError({'marks_awarded': 'Awarded marks must be between zero and maximum marks.'})
        if self.paper_question_id and self.max_marks != self.paper_question.marks:
            raise ValidationError({'max_marks': 'Maximum marks must match the released paper snapshot.'})
        if (
            self.sheet_id and self.paper_question_id
            and self.sheet.attempt.exam.paper_id != self.paper_question.paper_id
        ):
            raise ValidationError({'paper_question': 'Question must belong to the answer sheet exam.'})
        if self.paper_question_id and self.paper_question.question_type not in ('short_answer', 'long_answer'):
            raise ValidationError({'paper_question': 'Only subjective questions can be reviewed on an answer sheet.'})


class ExamActivityEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='exam_activity_events')
    exam = models.ForeignKey(
        ExamSchedule, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_events'
    )
    attempt = models.ForeignKey(
        ExamAttempt, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_events'
    )
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='exam_activity_events'
    )
    event_type = models.CharField(max_length=40, choices=ExamActivityType.choices, db_index=True)
    source = models.CharField(max_length=20, choices=ExamActivitySource.choices, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'exams_exam_activity_event'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['institute', 'created_at']),
            models.Index(fields=['attempt', 'event_type', 'created_at']),
        ]


class ExamIntegrityFlag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name='integrity_flags')
    code = models.CharField(max_length=60)
    explanation = models.TextField()
    status = models.CharField(
        max_length=20, choices=IntegrityFlagStatus.choices, default=IntegrityFlagStatus.OPEN, db_index=True
    )
    review_decision = models.TextField(blank=True, default='')
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_exam_integrity_flags'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'exams_exam_integrity_flag'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['attempt', 'code'], name='unique_attempt_integrity_flag')
        ]
        indexes = [models.Index(fields=['status', 'created_at'])]


class RevaluationRequestStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'


class RevaluationRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.PROTECT, related_name='revaluation_requests')
    paper_question = models.ForeignKey(
        'blueprints.GeneratedPaperQuestion', on_delete=models.PROTECT,
        related_name='revaluation_requests',
    )
    requested_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='revaluation_requests'
    )
    reason = models.TextField(max_length=5000)
    status = models.CharField(
        max_length=20, choices=RevaluationRequestStatus.choices,
        default=RevaluationRequestStatus.PENDING, db_index=True,
    )
    reviewer = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True,
        related_name='reviewed_revaluation_requests',
    )
    review_comment = models.TextField(blank=True, default='')
    corrected_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'exams_revaluation_request'
        ordering = ['-submitted_at']
        constraints = [
            models.UniqueConstraint(
                fields=['attempt', 'paper_question'], name='unique_attempt_question_revaluation'
            ),
        ]
        indexes = [models.Index(fields=['status', 'submitted_at'])]

    def clean(self):
        errors = {}
        if self.attempt_id and self.requested_by_id:
            if self.attempt.placement.student.user_id != self.requested_by_id:
                errors['requested_by'] = 'The request must be filed by the attempt owner.'
        if self.attempt_id and self.paper_question_id:
            if self.attempt.exam.paper_id != self.paper_question.paper_id:
                errors['paper_question'] = 'Question must belong to the attempt’s released paper.'
        if self.corrected_marks is not None and self.paper_question_id:
            minimum = (
                -self.paper_question.negative_marks
                if self.paper_question.question_type in ('mcq', 'true_false')
                else Decimal('0.00')
            )
            if self.corrected_marks < minimum or self.corrected_marks > self.paper_question.marks:
                errors['corrected_marks'] = 'Corrected marks are outside the permitted range.'
        if self.status == RevaluationRequestStatus.PENDING and (
            self.reviewer_id or self.decided_at or self.corrected_marks is not None
        ):
            errors['status'] = 'Pending requests cannot contain reviewer decisions or corrected marks.'
        if self.status == RevaluationRequestStatus.REJECTED and self.corrected_marks is not None:
            errors['corrected_marks'] = 'Rejected requests cannot change marks.'
        if self.status != RevaluationRequestStatus.PENDING and (
            not self.reviewer_id or not self.decided_at
        ):
            errors['status'] = 'A decided request must record its reviewer and decision time.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class RevaluationDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(RevaluationRequest, on_delete=models.PROTECT, related_name='decisions')
    reviewer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='revaluation_decisions')
    decision = models.CharField(max_length=20, choices=(
        (RevaluationRequestStatus.APPROVED, 'Approved'),
        (RevaluationRequestStatus.REJECTED, 'Rejected'),
    ))
    comment = models.TextField(max_length=5000)
    previous_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    corrected_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'exams_revaluation_decision'
        ordering = ['created_at']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Revaluation decision history is immutable.')
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Revaluation decision history is immutable.')


class ExamGrievance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.PROTECT, related_name='grievances')
    filed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='exam_grievances')
    reason = models.TextField(max_length=5000)
    status = models.CharField(
        max_length=20, choices=RevaluationRequestStatus.choices,
        default=RevaluationRequestStatus.PENDING, db_index=True,
    )
    reviewer = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True,
        related_name='reviewed_exam_grievances',
    )
    review_comment = models.TextField(blank=True, default='')
    filed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'exams_exam_grievance'
        ordering = ['-filed_at']
        constraints = [
            models.UniqueConstraint(fields=['attempt'], name='unique_exam_grievance_attempt')
        ]
        indexes = [models.Index(fields=['status', 'filed_at'])]

    def clean(self):
        if self.attempt_id and self.filed_by_id:
            if self.attempt.placement.student.user_id != self.filed_by_id:
                raise ValidationError({'filed_by': 'A grievance must be filed by the attempt owner.'})
        if self.status == RevaluationRequestStatus.PENDING and (
            self.reviewer_id or self.decided_at
        ):
            raise ValidationError('Pending grievances cannot contain a reviewer decision.')
        if self.status != RevaluationRequestStatus.PENDING and (
            not self.reviewer_id or not self.decided_at
        ):
            raise ValidationError('A decided grievance must record its reviewer and decision time.')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class ExamGrievanceDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grievance = models.ForeignKey(
        ExamGrievance, on_delete=models.PROTECT, related_name='decisions'
    )
    reviewer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='exam_grievance_decisions')
    decision = models.CharField(max_length=20, choices=(
        (RevaluationRequestStatus.APPROVED, 'Approved'),
        (RevaluationRequestStatus.REJECTED, 'Rejected'),
    ))
    comment = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'exams_exam_grievance_decision'
        ordering = ['created_at']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Grievance decision history is immutable.')
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Grievance decision history is immutable.')
