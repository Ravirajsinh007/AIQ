from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import MembershipStatus, RoleChoices
from apps.audit.services import record_audit_event
from apps.questions.models import (
    Question,
    QuestionStatus,
    QuestionType,
)

from .models import QuestionReviewRecord, ReviewDecision


@transaction.atomic
def submit_question_for_review(*, question, user, notes=''):
    locked = Question.objects.select_for_update().select_related(
        'institute', 'subject'
    ).filter(pk=question.pk).first()
    if locked is None:
        raise NotFound('Question not found.')
    membership = user.memberships.filter(
        institute_id=locked.institute_id,
        status=MembershipStatus.ACTIVE,
        role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER],
    ).first()
    if membership is None:
        raise PermissionDenied('You are not authorized to submit questions for this institute.')
    if membership.role == RoleChoices.TEACHER:
        if locked.created_by_id != user.id:
            raise PermissionDenied('You can only submit your own questions for review.')
    if locked.status not in [QuestionStatus.DRAFT, QuestionStatus.REJECTED]:
        raise ValidationError(
            f"Cannot submit question for review from {locked.status}. Only draft or rejected questions can be submitted for review."
        )
    if not locked.question_text.strip():
        raise ValidationError({'question_text': 'Question text cannot be empty.'})
    old_status = locked.status
    locked.status = QuestionStatus.UNDER_REVIEW
    locked.save(update_fields=['status', 'updated_at'])
    record = QuestionReviewRecord.objects.create(
        question=locked,
        reviewer=user,
        decision=ReviewDecision.SUBMIT,
        from_status=old_status,
        to_status=QuestionStatus.UNDER_REVIEW,
        general_notes=notes or f'Submitted for review from {old_status}',
        question_version=locked.current_version,
    )
    record_audit_event(
        action='question.submitted_for_review',
        resource_type='question',
        resource_id=locked.pk,
        actor=user,
        institute=locked.institute,
        metadata={'from_status': old_status, 'to_status': locked.status},
    )
    question.status = locked.status
    question.updated_at = locked.updated_at
    return record


@transaction.atomic
def apply_question_review_decision(*, serializer, user):
    question = serializer.validated_data['question']
    if user.is_platform_admin:
        raise PermissionDenied('Platform administrators cannot make institutional review decisions.')
    locked = Question.objects.select_for_update().select_related(
        'institute', 'subject'
    ).filter(pk=question.pk).first()
    if locked is None:
        raise NotFound('Question not found.')
    membership = user.memberships.filter(
        institute_id=locked.institute_id,
        status=MembershipStatus.ACTIVE,
        role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER],
    ).first()
    if membership is None:
        raise PermissionDenied('You are not authorized to review questions for this institute.')
    if locked.created_by_id == user.id:
        raise PermissionDenied('Authors cannot review their own questions.')
    if locked.status != QuestionStatus.UNDER_REVIEW:
        raise ValidationError('Only questions under review can receive a review decision.')

    decision = serializer.validated_data['decision']
    comment = serializer.validated_data.get('comment', '')
    transitions = {
        'approved': (QuestionStatus.APPROVED, ReviewDecision.APPROVE),
        'rejected': (QuestionStatus.REJECTED, ReviewDecision.REJECT),
        'needs_revision': (QuestionStatus.DRAFT, ReviewDecision.REQUEST_REVISION),
    }
    target_status, review_decision = transitions[decision]
    if decision == 'approved' and locked.question_type == QuestionType.MCQ and (
        locked.options.count() < 2 or not locked.options.filter(is_correct=True).exists()
    ):
        raise ValidationError('MCQ approval requires at least two options and a correct option.')
    if decision == 'approved' and locked.question_type == QuestionType.TRUE_FALSE and (
        locked.options.count() != 2 or locked.options.filter(is_correct=True).count() != 1
    ):
        raise ValidationError('True/False approval requires two options and exactly one correct option.')

    old_status = locked.status
    locked.status = target_status
    locked.save(update_fields=['status', 'updated_at'])
    record = QuestionReviewRecord.objects.create(
        question=locked,
        reviewer=user,
        decision=review_decision,
        from_status=old_status,
        to_status=target_status,
        rejection_reason=comment if decision == 'rejected' else '',
        revision_feedback=comment if decision == 'needs_revision' else '',
        general_notes=comment,
        question_version=locked.current_version,
    )
    from apps.audit.services import record_audit_event

    record_audit_event(
        action=f'question.{decision}',
        resource_type='question',
        resource_id=locked.pk,
        actor=user,
        institute=locked.institute,
        metadata={'from_status': old_status, 'to_status': target_status},
    )
    serializer.instance = serializer.save(reviewer=user)
    return record
