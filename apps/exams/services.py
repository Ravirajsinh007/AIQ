from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError as APIValidationError

from apps.accounts.models import MembershipStatus, RoleChoices
from apps.academics.models import (
    AcademicStatus,
    PlacementStatus,
    ProgramSemesterSubject,
    StudentAcademicPlacement,
    StudentSubjectEnrollment,
)
from apps.blueprints.models import GeneratedPaperQuestion

from .models import (
    ExamActivityEvent,
    ExamActivitySource,
    ExamActivityType,
    ExamAnswer,
    ExamAttempt,
    ExamAttemptStatus,
    ExamAvailabilityState,
    ExamIntegrityFlag,
    ExamSchedule,
    ExamScheduleStatus,
    IntegrityFlagStatus,
)

CLIENT_EVENT_TYPES = {
    ExamActivityType.VISIBILITY_CHANGED,
    ExamActivityType.FULLSCREEN_EXIT,
    ExamActivityType.RECONNECT,
}
MAX_SHORT_ANSWER_LENGTH = 20000
MAX_CODE_LENGTH = 50000


def active_student_membership(user, institute_id):
    return user.memberships.filter(
        institute_id=institute_id,
        role=RoleChoices.STUDENT,
        status=MembershipStatus.ACTIVE,
    ).first()


def eligible_placements(exam, user, at=None):
    at = at or timezone.now()
    membership = active_student_membership(user, exam.institute_id)
    if membership is None:
        return StudentAcademicPlacement.objects.none()
    placements = StudentAcademicPlacement.objects.filter(
        student=membership,
        status=PlacementStatus.ACTIVE,
        effective_start_date__lte=timezone.localdate(at),
    ).filter(Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=timezone.localdate(at)))
    placements = placements.filter(batch_id=exam.batch_id)
    if exam.section_id:
        placements = placements.filter(section_id=exam.section_id)

    blueprint = exam.paper.blueprint
    # New records use explicit student enrollments; legacy placements retain curriculum-based access.
    has_explicit_enrollments = StudentSubjectEnrollment.objects.filter(
        student_id=OuterRef('student_id'),
        batch_id=OuterRef('batch_id'),
    )
    explicit_subject_enrollment = StudentSubjectEnrollment.objects.filter(
        student_id=OuterRef('student_id'),
        batch_id=OuterRef('batch_id'),
        subject_id=exam.paper.subject_id,
        status=AcademicStatus.ACTIVE,
    )
    curriculum_enrollment = ProgramSemesterSubject.objects.filter(
        program_id=OuterRef('program_id'),
        semester_id=OuterRef('semester_id'),
        subject_id=exam.paper.subject_id,
    )
    placements = placements.annotate(
        _has_explicit_enrollments=Exists(has_explicit_enrollments),
        _has_explicit_subject=Exists(explicit_subject_enrollment),
        _has_legacy_curriculum=Exists(curriculum_enrollment),
    )
    legacy_curriculum_access = Q(
        _has_explicit_enrollments=False,
        _has_legacy_curriculum=True,
    )
    if blueprint.program_id:
        legacy_curriculum_access &= Q(program_id=blueprint.program_id)
    if blueprint.semester_id:
        legacy_curriculum_access &= Q(semester_id=blueprint.semester_id)
    return placements.filter(
        Q(_has_explicit_enrollments=True, _has_explicit_subject=True)
        | legacy_curriculum_access
    )


def find_eligible_placement(exam, user, at=None):
    return eligible_placements(exam, user, at).select_related(
        'student', 'batch', 'section', 'program', 'semester'
    ).first()


def append_event(*, exam, attempt, actor, event_type, source, metadata=None):
    return ExamActivityEvent.objects.create(
        institute_id=exam.institute_id,
        exam=exam,
        attempt=attempt,
        actor=actor,
        event_type=event_type,
        source=source,
        metadata=metadata or {},
    )


def _auto_submit_locked(attempt, at=None):
    at = at or timezone.now()
    if attempt.status != ExamAttemptStatus.IN_PROGRESS or at < attempt.deadline_at:
        return False
    attempt.status = ExamAttemptStatus.AUTO_SUBMITTED
    attempt.submitted_at = at
    attempt.save(update_fields=['status', 'submitted_at', 'updated_at'])
    from .evaluation_services import grade_objective_answers

    grade_objective_answers(attempt)
    append_event(
        exam=attempt.exam,
        attempt=attempt,
        actor=None,
        event_type=ExamActivityType.ATTEMPT_AUTO_SUBMITTED,
        source=ExamActivitySource.SERVER_VERIFIED,
        metadata={'reason': 'deadline_reached'},
    )
    return True


def start_or_resume_exam(exam_id, user):
    ineligible = False
    with transaction.atomic():
        try:
            exam = ExamSchedule.objects.select_for_update().select_related(
                'paper__blueprint'
            ).get(
                pk=exam_id,
                status=ExamScheduleStatus.SCHEDULED,
                published=True,
            )
        except ExamSchedule.DoesNotExist as exc:
            raise NotFound('Exam not found.') from exc

        now = timezone.now()
        if exam.availability_state(now) != ExamAvailabilityState.AVAILABLE:
            raise APIValidationError({'detail': 'The exam is outside its scheduled access window.'})
        placement = find_eligible_placement(exam, user, now)
        if placement is None:
            ineligible = True
        else:
            attempt = ExamAttempt.objects.select_for_update().filter(
                exam=exam, placement=placement, status=ExamAttemptStatus.IN_PROGRESS
            ).first()
            if attempt:
                if _auto_submit_locked(attempt, now):
                    return attempt
                event_type = ExamActivityType.ATTEMPT_RESUMED
            else:
                if exam.attempts.filter(placement=placement).exists():
                    raise APIValidationError({'detail': 'An attempt has already been submitted for this exam.'})
                try:
                    with transaction.atomic():
                        attempt = ExamAttempt.objects.create(
                            exam=exam, placement=placement, started_at=now
                        )
                except IntegrityError:
                    attempt = ExamAttempt.objects.select_for_update().filter(
                        exam=exam, placement=placement, status=ExamAttemptStatus.IN_PROGRESS
                    ).first()
                    if attempt is None:
                        raise APIValidationError(
                            {'detail': 'An attempt has already been submitted for this exam.'}
                        )
                    event_type = ExamActivityType.ATTEMPT_RESUMED
                else:
                    event_type = ExamActivityType.ATTEMPT_STARTED

            append_event(
                exam=exam,
                attempt=attempt,
                actor=user,
                event_type=event_type,
                source=ExamActivitySource.SERVER_VERIFIED,
            )
    if ineligible:
        ExamActivityEvent.objects.create(
            institute=exam.institute,
            exam=exam,
            actor=user,
            event_type=ExamActivityType.SECURITY_VIOLATION,
            source=ExamActivitySource.SERVER_VERIFIED,
            metadata={'reason': 'ineligible_exam_access'},
        )
        raise PermissionDenied('You are not eligible to access this exam.')
    return attempt


def get_owned_attempt(attempt_id, user, *, lock=False):
    attempts = ExamAttempt.objects.select_related(
        'exam__paper__blueprint', 'placement__student__user'
    )
    if lock:
        attempts = attempts.select_for_update()
    attempt = attempts.filter(
        pk=attempt_id,
        placement__student__user=user,
        placement__student__status=MembershipStatus.ACTIVE,
        placement__student__role=RoleChoices.STUDENT,
        placement__status=PlacementStatus.ACTIVE,
    ).first()
    if attempt is None:
        membership = user.memberships.filter(
            role=RoleChoices.STUDENT, status=MembershipStatus.ACTIVE
        ).first()
        if membership:
            ExamActivityEvent.objects.create(
                institute=membership.institute,
                actor=user,
                event_type=ExamActivityType.SECURITY_VIOLATION,
                source=ExamActivitySource.SERVER_VERIFIED,
                metadata={'reason': 'attempt_access_denied'},
            )
        raise NotFound('Attempt not found.')
    return attempt


def ensure_attempt_writable(attempt, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        current = ExamAttempt.objects.select_for_update().select_related('exam__paper').get(pk=attempt.pk)
        if current.status != ExamAttemptStatus.IN_PROGRESS:
            raise APIValidationError({'detail': 'This attempt no longer accepts answer changes.'})
        return not _auto_submit_locked(current, now)


def _validate_response(paper_question, response):
    question_type = paper_question.question_type
    if question_type in ('mcq', 'true_false'):
        if not isinstance(response, str) or not response:
            raise APIValidationError({'response': 'Select one valid option key.'})
        option_keys = {
            item.get('option_key', item.get('key'))
            for item in (paper_question.options_snapshot or [])
            if isinstance(item, dict)
        }
        if response not in option_keys:
            raise APIValidationError({'response': 'Selected option does not belong to this question.'})
        return response
    if question_type == 'coding':
        if not isinstance(response, dict) or set(response) - {'code', 'language'}:
            raise APIValidationError({'response': 'Coding answers must contain only code and language.'})
        code = response.get('code')
        language = response.get('language')
        if not isinstance(code, str) or len(code) > MAX_CODE_LENGTH:
            raise APIValidationError({'response': f'Code must be text up to {MAX_CODE_LENGTH} characters.'})
        if not isinstance(language, str) or not language or len(language) > 50:
            raise APIValidationError({'response': 'A valid programming language is required.'})
        return {'code': code, 'language': language}
    if not isinstance(response, str) or len(response) > MAX_SHORT_ANSWER_LENGTH:
        raise APIValidationError(
            {'response': f'Answer must be text up to {MAX_SHORT_ANSWER_LENGTH} characters.'}
        )
    return response


def save_answer(attempt_id, user, question_id, response):
    get_owned_attempt(attempt_id, user)
    with transaction.atomic():
        attempt = get_owned_attempt(attempt_id, user, lock=True)
        writable = ensure_attempt_writable(attempt)
        if not writable:
            answer = None
        else:
            paper_question = GeneratedPaperQuestion.objects.filter(
                pk=question_id, paper_id=attempt.exam.paper_id
            ).first()
            if paper_question is None:
                raise APIValidationError({'question': 'Question is not part of this exam paper.'})
            response = _validate_response(paper_question, response)
            answer = ExamAnswer.objects.select_for_update().filter(
                attempt=attempt, paper_question=paper_question
            ).first()
            changed = answer is None or answer.response != response
            if answer is None:
                answer = ExamAnswer.objects.create(
                    attempt=attempt, paper_question=paper_question, response=response
                )
            elif changed:
                answer.response = response
                answer.revision += 1
                answer.save(update_fields=['response', 'revision', 'updated_at'])
            if changed:
                append_event(
                    exam=attempt.exam,
                    attempt=attempt,
                    actor=user,
                    event_type=ExamActivityType.ANSWER_SAVED,
                    source=ExamActivitySource.SERVER_VERIFIED,
                    metadata={'paper_question_id': str(paper_question.id), 'revision': answer.revision},
                )
    if answer is None:
        raise APIValidationError({'detail': 'The exam deadline has passed; the attempt was auto-submitted.'})
    return answer


def submit_attempt(attempt_id, user):
    get_owned_attempt(attempt_id, user)
    with transaction.atomic():
        attempt = get_owned_attempt(attempt_id, user, lock=True)
        if attempt.status in (ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED):
            return attempt
        if not ensure_attempt_writable(attempt):
            attempt.refresh_from_db()
            return attempt
        attempt.status = ExamAttemptStatus.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=['status', 'submitted_at', 'updated_at'])
        from .evaluation_services import grade_objective_answers

        grade_objective_answers(attempt)
        append_event(
            exam=attempt.exam,
            attempt=attempt,
            actor=user,
            event_type=ExamActivityType.ATTEMPT_SUBMITTED,
            source=ExamActivitySource.SERVER_VERIFIED,
        )
        return attempt


def report_client_event(attempt_id, user, event_type, metadata):
    if event_type not in CLIENT_EVENT_TYPES:
        raise APIValidationError({'event_type': 'This client-reported event type is not accepted.'})
    if not isinstance(metadata, dict):
        raise APIValidationError({'metadata': 'Metadata must be a JSON object.'})
    allowed_keys = {
        ExamActivityType.VISIBILITY_CHANGED: {'state'},
        ExamActivityType.FULLSCREEN_EXIT: set(),
        ExamActivityType.RECONNECT: {'count'},
    }[event_type]
    if set(metadata) - allowed_keys:
        raise APIValidationError({'metadata': 'Metadata contains unsupported fields.'})
    if event_type == ExamActivityType.VISIBILITY_CHANGED and metadata.get('state') not in {'hidden', 'visible'}:
        raise APIValidationError({'metadata': {'state': 'Must be hidden or visible.'}})
    if event_type == ExamActivityType.RECONNECT:
        count = metadata.get('count', 1)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1 or count > 100:
            raise APIValidationError({'metadata': {'count': 'Must be an integer from 1 to 100.'}})

    get_owned_attempt(attempt_id, user)
    with transaction.atomic():
        attempt = get_owned_attempt(attempt_id, user, lock=True)
        if not ensure_attempt_writable(attempt):
            return False
        append_event(
            exam=attempt.exam,
            attempt=attempt,
            actor=user,
            event_type=event_type,
            source=ExamActivitySource.CLIENT_REPORTED,
            metadata=metadata,
        )
        evaluate_integrity_patterns(attempt)
        return True


def evaluate_integrity_patterns(attempt):
    now = timezone.now()
    window_start = now - timedelta(minutes=10)
    hidden_count = attempt.activity_events.filter(
        source=ExamActivitySource.CLIENT_REPORTED,
        event_type=ExamActivityType.VISIBILITY_CHANGED,
        metadata__state='hidden',
        created_at__gte=window_start,
    ).count()
    if hidden_count >= 5:
        ExamIntegrityFlag.objects.get_or_create(
            attempt=attempt,
            code='repeated_visibility_changes',
            defaults={
                'explanation': (
                    f'{hidden_count} client-reported transitions to hidden visibility were received '
                    'within 10 minutes. This is an unverified signal and requires human review.'
                )
            },
        )
    reconnect_count = attempt.activity_events.filter(
        source=ExamActivitySource.CLIENT_REPORTED,
        event_type=ExamActivityType.RECONNECT,
        created_at__gte=window_start,
    ).count()
    if reconnect_count >= 10:
        ExamIntegrityFlag.objects.get_or_create(
            attempt=attempt,
            code='repeated_reconnect_reports',
            defaults={
                'explanation': (
                    f'{reconnect_count} client-reported reconnect events were received within 10 minutes. '
                    'These reports are unverified and require human review.'
                )
            },
        )


@transaction.atomic
def review_integrity_flag(flag, reviewer, status, decision):
    if status not in (IntegrityFlagStatus.REVIEWED, IntegrityFlagStatus.DISMISSED):
        raise APIValidationError({'status': 'Review status must be reviewed or dismissed.'})
    if not decision.strip():
        raise APIValidationError({'review_decision': 'A review decision is required.'})
    flag.status = status
    flag.review_decision = decision.strip()
    flag.reviewed_by = reviewer
    flag.reviewed_at = timezone.now()
    flag.save(update_fields=['status', 'review_decision', 'reviewed_by', 'reviewed_at'])
    append_event(
        exam=flag.attempt.exam,
        attempt=flag.attempt,
        actor=reviewer,
        event_type=ExamActivityType.INTEGRITY_FLAG_REVIEWED,
        source=ExamActivitySource.SERVER_VERIFIED,
        metadata={'flag_id': str(flag.id), 'decision': status},
    )
    return flag


@transaction.atomic
def process_expired_attempts():
    now = timezone.now()
    attempt_ids = ExamAttempt.objects.filter(
        status=ExamAttemptStatus.IN_PROGRESS
    ).values_list('id', flat=True)
    submitted_count = 0
    for attempt_id in attempt_ids.iterator():
        attempt = ExamAttempt.objects.select_for_update().select_related('exam__paper').get(pk=attempt_id)
        submitted_count += _auto_submit_locked(attempt, now)
    return submitted_count
