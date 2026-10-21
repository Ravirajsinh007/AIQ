from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import record_audit_event

from .models import (
    ExamAnswerEvaluation,
    ExamAttempt,
    ExamAttemptStatus,
    ExamGrievance,
    ExamGrievanceDecision,
    HandwrittenAnswerEvaluation,
    RevaluationDecision,
    RevaluationRequest,
    RevaluationRequestStatus,
)


def submit_exam_grievance(*, attempt_id, user, reason):
    try:
        with transaction.atomic():
            attempt = ExamAttempt.objects.select_for_update().select_related(
                'exam__institute'
            ).get(pk=attempt_id)
            if attempt.status not in (ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED):
                raise ValidationError({'attempt': 'A grievance can be filed only after submission.'})
            if not attempt.exam.revaluation_opens_at or not attempt.exam.revaluation_closes_at:
                raise ValidationError({'detail': 'A grievance window has not been configured for this exam.'})
            now = timezone.now()
            if not attempt.exam.revaluation_opens_at <= now <= attempt.exam.revaluation_closes_at:
                raise ValidationError({'detail': 'The grievance submission window is closed.'})
            if ExamGrievance.objects.filter(attempt=attempt).exists():
                raise ValidationError({'attempt': 'A grievance already exists for this exam attempt.'})
            grievance = ExamGrievance.objects.create(
                attempt=attempt, filed_by=user, reason=reason
            )
            record_audit_event(
                action='exam.grievance.submitted',
                resource_type='exam_grievance',
                resource_id=grievance.pk,
                actor=user,
                institute=attempt.exam.institute,
            )
            return grievance
    except IntegrityError as exc:
        raise ValidationError({'attempt': 'A grievance already exists for this exam attempt.'}) from exc


@transaction.atomic
def decide_exam_grievance(grievance_id, reviewer, *, decision, comment):
    grievance = ExamGrievance.objects.select_for_update().select_related(
        'attempt__exam__institute'
    ).get(pk=grievance_id)
    if grievance.status != RevaluationRequestStatus.PENDING:
        raise ValidationError({'detail': 'This grievance has already been decided.'})
    if grievance.filed_by_id == reviewer.pk:
        raise ValidationError({'detail': 'A reviewer cannot decide their own grievance.'})
    grievance.status = decision
    grievance.reviewer = reviewer
    grievance.review_comment = comment.strip()
    grievance.decided_at = timezone.now()
    grievance.full_clean()
    grievance.save(update_fields=['status', 'reviewer', 'review_comment', 'decided_at'])
    ExamGrievanceDecision.objects.create(
        grievance=grievance, reviewer=reviewer,
        decision=decision, comment=grievance.review_comment,
    )
    record_audit_event(
        action='exam.grievance.decided',
        resource_type='exam_grievance',
        resource_id=grievance.pk,
        actor=reviewer,
        institute=grievance.attempt.exam.institute,
        metadata={
            'from_status': RevaluationRequestStatus.PENDING,
            'to_status': decision,
            'changed_fields': ['status', 'review_comment'],
        },
    )
    return grievance


def submit_revaluation_request(*, attempt_id, question_id, user, reason):
    try:
        with transaction.atomic():
            attempt = ExamAttempt.objects.select_for_update().select_related(
                'exam__institute', 'exam__paper', 'placement__student'
            ).get(pk=attempt_id)
            if attempt.status not in (ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED):
                raise ValidationError({'attempt': 'Revaluation is available only after submission.'})
            if not attempt.exam.revaluation_opens_at or not attempt.exam.revaluation_closes_at:
                raise ValidationError({'detail': 'A revaluation window has not been configured for this exam.'})
            now = timezone.now()
            if not attempt.exam.revaluation_opens_at <= now <= attempt.exam.revaluation_closes_at:
                raise ValidationError({'detail': 'The revaluation submission window is closed.'})
            question = attempt.exam.paper.paper_questions.filter(pk=question_id).first()
            if question is None:
                raise ValidationError({'question': 'Question is not part of this exam.'})
            if RevaluationRequest.objects.filter(
                attempt=attempt, paper_question=question
            ).exists():
                raise ValidationError({
                    'question': 'A revaluation request already exists for this attempt and question.'
                })
            request = RevaluationRequest.objects.create(
                attempt=attempt,
                paper_question=question,
                requested_by=user,
                reason=reason,
            )
            record_audit_event(
                action='exam.revaluation.submitted',
                resource_type='revaluation_request',
                resource_id=request.pk,
                actor=user,
                institute=attempt.exam.institute,
            )
            return request
    except IntegrityError as exc:
        raise ValidationError({
            'question': 'A revaluation request already exists for this attempt and question.'
        }) from exc


def current_question_marks(attempt, paper_question):
    handwritten = HandwrittenAnswerEvaluation.objects.filter(
        sheet__attempt=attempt,
        paper_question=paper_question,
        sheet__status='reviewed',
    ).first()
    if handwritten:
        return handwritten.marks_awarded
    evaluation = ExamAnswerEvaluation.objects.filter(
        answer__attempt=attempt,
        answer__paper_question=paper_question,
        status='graded',
    ).first()
    if evaluation and evaluation.marks_awarded is not None:
        return evaluation.marks_awarded
    return Decimal('0.00')


@transaction.atomic
def decide_revaluation(request_id, reviewer, *, decision, comment, corrected_marks=None):
    request = RevaluationRequest.objects.select_for_update().select_related(
        'attempt__exam__institute', 'paper_question'
    ).get(pk=request_id)
    if request.status != RevaluationRequestStatus.PENDING:
        raise ValidationError({'detail': 'This revaluation request has already been decided.'})
    if request.requested_by_id == reviewer.pk:
        raise ValidationError({'detail': 'A reviewer cannot decide their own revaluation request.'})
    if decision == RevaluationRequestStatus.REJECTED and corrected_marks is not None:
        raise ValidationError({'corrected_marks': 'Rejected requests cannot change marks.'})

    previous_marks = current_question_marks(request.attempt, request.paper_question)
    request.status = decision
    request.reviewer = reviewer
    request.review_comment = comment.strip()
    request.corrected_marks = corrected_marks
    request.decided_at = timezone.now()
    request.full_clean()
    request.save(update_fields=[
        'status', 'reviewer', 'review_comment', 'corrected_marks', 'decided_at',
    ])
    RevaluationDecision.objects.create(
        request=request,
        reviewer=reviewer,
        decision=decision,
        comment=request.review_comment,
        previous_marks=previous_marks,
        corrected_marks=corrected_marks,
    )
    record_audit_event(
        action='exam.revaluation.decided',
        resource_type='revaluation_request',
        resource_id=request.pk,
        actor=reviewer,
        institute=request.attempt.exam.institute,
        metadata={
            'from_status': RevaluationRequestStatus.PENDING,
            'to_status': decision,
            'changed_fields': ['status', 'review_comment', 'corrected_marks'],
        },
    )
    return request
