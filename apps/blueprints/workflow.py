from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import MembershipStatus, RoleChoices
from apps.audit.services import record_audit_event

from .models import (
    GeneratedPaper,
    GeneratedPaperQuestion,
    GeneratedPaperStatus,
    PaperWorkflowStatus,
)


MANAGER_ROLES = (RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF)


def _membership(user, institute_id):
    if user.is_platform_admin:
        return None
    return user.memberships.filter(
        institute_id=institute_id,
        status=MembershipStatus.ACTIVE,
        role__in=[*MANAGER_ROLES, RoleChoices.TEACHER],
    ).first()


def _require_manager(user, institute_id):
    membership = _membership(user, institute_id)
    if membership is None or membership.role not in MANAGER_ROLES:
        raise PermissionDenied('Institute administrator or exam staff permission is required.')
    return membership


def _require_paper_editor(user, paper):
    membership = _membership(user, paper.institute_id)
    if membership is None:
        raise PermissionDenied('You are not authorized for this institute.')
    if membership.role in MANAGER_ROLES:
        return
    assigned = membership.teaching_assignments.filter(
        subject=paper.subject,
        status='active',
    ).exists()
    if not assigned and paper.created_by_id != user.id:
        raise PermissionDenied('Only the paper creator or an assigned teacher may submit this paper.')


def submit_paper_for_review(paper_id, user):
    with transaction.atomic():
        paper = GeneratedPaper.objects.select_for_update().select_related(
            'institute', 'subject', 'created_by'
        ).filter(pk=paper_id, status=GeneratedPaperStatus.COMPLETED).first()
        if paper is None:
            raise NotFound('Generated paper not found.')
        _require_paper_editor(user, paper)
        if paper.workflow_status not in [PaperWorkflowStatus.DRAFT, PaperWorkflowStatus.REJECTED]:
            raise ValidationError('Only draft or rejected papers can be submitted for review.')
        old_status = paper.workflow_status
        paper.workflow_status = PaperWorkflowStatus.SUBMITTED
        paper.submitted_at = timezone.now()
        paper.rejection_reason = ''
        paper.save(update_fields=['workflow_status', 'submitted_at', 'rejection_reason', 'updated_at'])
        record_audit_event(
            action='paper.submitted',
            resource_type='generated_paper',
            resource_id=paper.pk,
            actor=user,
            institute=paper.institute,
            metadata={'from_status': old_status, 'to_status': paper.workflow_status},
        )
        return paper


def review_paper(paper_id, user, *, approve, rejection_reason=''):
    with transaction.atomic():
        paper = GeneratedPaper.objects.select_for_update().select_related(
            'institute', 'created_by'
        ).filter(pk=paper_id, status=GeneratedPaperStatus.COMPLETED).first()
        if paper is None:
            raise NotFound('Generated paper not found.')
        _require_manager(user, paper.institute_id)
        if paper.workflow_status != PaperWorkflowStatus.SUBMITTED:
            raise ValidationError('Only papers submitted for review can be approved or rejected.')
        if paper.created_by_id == user.id:
            raise PermissionDenied('The paper creator cannot make formal review decisions on their own paper.')
        if not approve and not rejection_reason.strip():
            raise ValidationError({'rejection_reason': 'A rejection reason is required.'})
        old_status = paper.workflow_status
        paper.workflow_status = PaperWorkflowStatus.APPROVED if approve else PaperWorkflowStatus.REJECTED
        paper.approved_by = user if approve else None
        paper.approved_at = timezone.now() if approve else None
        paper.rejection_reason = '' if approve else rejection_reason.strip()
        paper.save(update_fields=[
            'workflow_status', 'approved_by', 'approved_at', 'rejection_reason', 'updated_at'
        ])
        record_audit_event(
            action='paper.approved' if approve else 'paper.rejected',
            resource_type='generated_paper',
            resource_id=paper.pk,
            actor=user,
            institute=paper.institute,
            metadata={'from_status': old_status, 'to_status': paper.workflow_status},
        )
        return paper


def schedule_paper_release(paper_id, user, release_at):
    with transaction.atomic():
        paper = GeneratedPaper.objects.select_for_update().select_related(
            'institute'
        ).filter(pk=paper_id, status=GeneratedPaperStatus.COMPLETED).first()
        if paper is None:
            raise NotFound('Generated paper not found.')
        _require_manager(user, paper.institute_id)
        if paper.workflow_status != PaperWorkflowStatus.APPROVED:
            raise ValidationError('Only approved papers can be scheduled for release.')
        if release_at < timezone.now():
            raise ValidationError({'release_at': 'Release time must be in the future.'})
        paper.workflow_status = PaperWorkflowStatus.SCHEDULED
        paper.scheduled_release_at = release_at
        paper.save(update_fields=['workflow_status', 'scheduled_release_at', 'updated_at'])
        record_audit_event(
            action='paper.release_scheduled',
            resource_type='generated_paper',
            resource_id=paper.pk,
            actor=user,
            institute=paper.institute,
            metadata={
                'from_status': PaperWorkflowStatus.APPROVED,
                'to_status': paper.workflow_status,
                'scheduled_for': release_at.isoformat(),
            },
        )
        return paper


def release_paper(paper_id, *, user=None, at=None):
    at = at or timezone.now()
    with transaction.atomic():
        paper = GeneratedPaper.objects.select_for_update().select_related('institute').filter(
            pk=paper_id,
            status=GeneratedPaperStatus.COMPLETED,
        ).first()
        if paper is None:
            raise NotFound('Generated paper not found.')
        if user is not None:
            _require_manager(user, paper.institute_id)
        if paper.workflow_status == PaperWorkflowStatus.RELEASED:
            return paper
        if paper.workflow_status != PaperWorkflowStatus.SCHEDULED:
            raise ValidationError('Only scheduled papers can be released.')
        if paper.scheduled_release_at is None or at < paper.scheduled_release_at:
            raise ValidationError('The scheduled release time has not been reached.')
        old_status = paper.workflow_status
        paper.workflow_status = PaperWorkflowStatus.RELEASED
        paper.released_at = at
        paper.save(update_fields=['workflow_status', 'released_at', 'updated_at'])
        record_audit_event(
            action='paper.released',
            resource_type='generated_paper',
            resource_id=paper.pk,
            actor=user,
            institute=paper.institute,
            metadata={'from_status': old_status, 'to_status': paper.workflow_status},
        )
        return paper


def process_due_paper_releases(*, at=None):
    at = at or timezone.now()
    paper_ids = list(GeneratedPaper.objects.filter(
        workflow_status=PaperWorkflowStatus.SCHEDULED,
        scheduled_release_at__lte=at,
    ).values_list('id', flat=True))
    released = 0
    for paper_id in paper_ids:
        try:
            release_paper(paper_id, at=at)
        except ValidationError:
            continue
        else:
            released += 1
    return released


def archive_paper(paper_id, user):
    with transaction.atomic():
        paper = GeneratedPaper.objects.select_for_update().select_related('institute').filter(
            pk=paper_id,
            status=GeneratedPaperStatus.COMPLETED,
        ).first()
        if paper is None:
            raise NotFound('Generated paper not found.')
        _require_manager(user, paper.institute_id)
        if paper.workflow_status == PaperWorkflowStatus.ARCHIVED:
            return paper
        if paper.exam_schedules.filter(ends_at__gt=timezone.now(), status='scheduled').exists():
            raise ValidationError('A paper with a current or upcoming exam schedule cannot be archived.')
        if paper.workflow_status == PaperWorkflowStatus.SUBMITTED:
            raise ValidationError('A paper under review cannot be archived.')
        old_status = paper.workflow_status
        paper.workflow_status = PaperWorkflowStatus.ARCHIVED
        paper.archived_at = timezone.now()
        paper.save(update_fields=['workflow_status', 'archived_at', 'updated_at'])
        record_audit_event(
            action='paper.archived',
            resource_type='generated_paper',
            resource_id=paper.pk,
            actor=user,
            institute=paper.institute,
            metadata={'from_status': old_status, 'to_status': paper.workflow_status},
        )
        return paper


@transaction.atomic
def create_paper_amendment(paper_id, user, *, title, reason, question_edits):
    source = GeneratedPaper.objects.select_for_update().select_related(
        'institute', 'blueprint', 'subject'
    ).filter(pk=paper_id, status=GeneratedPaperStatus.COMPLETED).first()
    if source is None:
        raise NotFound('Generated paper not found.')
    _require_paper_editor(user, source)
    if source.workflow_status in [PaperWorkflowStatus.DRAFT, PaperWorkflowStatus.SUBMITTED]:
        raise ValidationError('Only rejected, approved, released, or archived papers can be amended.')
    if source.exam_schedules.filter(ends_at__gt=timezone.now(), status='scheduled').exists():
        raise ValidationError('A paper with a current or upcoming exam schedule cannot be amended.')
    if not reason.strip():
        raise ValidationError({'reason': 'An amendment reason is required.'})

    questions = list(source.paper_questions.order_by('question_number'))
    edits_by_number = {item['question_number']: item for item in question_edits}
    unknown_numbers = set(edits_by_number) - {question.question_number for question in questions}
    if unknown_numbers:
        raise ValidationError({'question_edits': 'An edited question number does not exist in this paper.'})
    resulting_marks = sum(
        (edits_by_number.get(question.question_number, {}).get('marks', question.marks) for question in questions),
        Decimal('0.00'),
    )
    if resulting_marks != source.total_marks:
        raise ValidationError({'question_edits': 'Amended question marks must continue to equal the paper total.'})
    for question in questions:
        edit = edits_by_number.get(question.question_number, {})
        if edit.get('negative_marks', question.negative_marks) > edit.get('marks', question.marks):
            raise ValidationError({'question_edits': 'Negative marks cannot exceed marks.'})
    if not edits_by_number and not title.strip():
        raise ValidationError('Provide a new title or at least one question edit.')

    source.blueprint.__class__.objects.select_for_update().get(pk=source.blueprint_id)
    version = (GeneratedPaper.objects.filter(blueprint=source.blueprint).aggregate(
        latest=Max('generation_version')
    )['latest'] or 0) + 1
    amended = GeneratedPaper.objects.create(
        institute=source.institute,
        blueprint=source.blueprint,
        title=title.strip() or source.title,
        subject=source.subject,
        total_marks=source.total_marks,
        duration_minutes=source.duration_minutes,
        status=GeneratedPaperStatus.COMPLETED,
        workflow_status=PaperWorkflowStatus.DRAFT,
        generation_version=version,
        blueprint_snapshot=source.blueprint_snapshot,
        validation_report=source.validation_report,
        created_by=user,
        supersedes=source,
        amendment_reason=reason.strip(),
    )
    for question in questions:
        edit = edits_by_number.get(question.question_number, {})
        GeneratedPaperQuestion.objects.create(
            paper=amended,
            section_name=question.section_name,
            section_order=question.section_order,
            question_number=question.question_number,
            question=question.question,
            question_version=question.question_version,
            question_type=question.question_type,
            question_text=edit.get('question_text', question.question_text),
            marks=edit.get('marks', question.marks),
            negative_marks=edit.get('negative_marks', question.negative_marks),
            difficulty=question.difficulty,
            bloom_taxonomy=question.bloom_taxonomy,
            options_snapshot=edit.get('options_snapshot', question.options_snapshot),
            rubric_snapshot=edit.get('rubric_snapshot', question.rubric_snapshot),
            provenance_snapshot=question.provenance_snapshot,
            test_cases_snapshot=question.test_cases_snapshot,
            code_metadata_snapshot=question.code_metadata_snapshot,
        )
    record_audit_event(
        action='paper.amended',
        resource_type='generated_paper',
        resource_id=amended.pk,
        actor=user,
        institute=source.institute,
        metadata={
            'from_status': source.workflow_status,
            'to_status': amended.workflow_status,
            'generation_version': amended.generation_version,
            'question_count': len(questions),
        },
    )
    return amended
