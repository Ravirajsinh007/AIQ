import hashlib
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError as APIValidationError

from apps.audit.services import record_audit_event

from .models import (
    CodingSubmission,
    CodingSubmissionStatus,
    EvaluationStatus,
    ExamAnswer,
    ExamAnswerEvaluation,
    ExamAttempt,
    ExamAttemptStatus,
    HandwrittenAnswerEvaluation,
    HandwrittenAnswerSheet,
    HandwrittenSheetStatus,
)
from .provider_services import (
    CodeExecutionProvider,
    OCRProvider,
    ProviderConfigurationError,
    ProviderExecutionError,
)

MAX_CODE_LENGTH = 50_000
MAX_HANDWRITTEN_FILE_BYTES = 20 * 1024 * 1024
ALLOWED_HANDWRITTEN_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}


def grade_objective_answers(attempt):
    if attempt.status not in (ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED):
        return
    questions = attempt.exam.paper.paper_questions.filter(
        question_type__in=('mcq', 'true_false')
    )
    for question in questions:
        answer, _ = ExamAnswer.objects.select_for_update().get_or_create(
            attempt=attempt,
            paper_question=question,
            defaults={'response': ''},
        )
        options = question.options_snapshot
        options = options if isinstance(options, list) else []
        option = next(
            (
                item for item in options
                if isinstance(item, dict)
                and item.get('option_key', item.get('key')) == answer.response
            ),
            None,
        )
        if answer.response and (
            option is None
            or not options
            or any(
                not isinstance(item, dict) or not isinstance(item.get('is_correct'), bool)
                for item in options
            )
        ):
            evaluation, created = ExamAnswerEvaluation.objects.get_or_create(
                answer=answer,
                defaults={
                    'status': EvaluationStatus.HUMAN_REVIEW,
                    'marks_awarded': None,
                    'max_marks': question.marks,
                    'grading_method': 'objective',
                    'details': {'reason': 'answer_key_missing_from_released_snapshot'},
                },
            )
            if created:
                record_audit_event(
                    action='answer.evaluation_review_required',
                    resource_type='exam_answer_evaluation',
                    resource_id=evaluation.pk,
                    actor=None,
                    institute=attempt.exam.institute,
                )
            continue
        correct = bool(option and option.get('is_correct') is True)
        marks = (
            question.marks if correct
            else -question.negative_marks if answer.response
            else Decimal('0.00')
        )
        evaluation, created = ExamAnswerEvaluation.objects.get_or_create(
            answer=answer,
            defaults={
                'status': EvaluationStatus.GRADED,
                'marks_awarded': marks,
                'max_marks': question.marks,
                'grading_method': 'objective',
                'evaluated_at': timezone.now(),
                'details': {'correct': correct},
            },
        )
        if not created and evaluation.grading_method == 'objective':
            continue
        if created:
            record_audit_event(
                action='answer.evaluated',
                resource_type='exam_answer_evaluation',
                resource_id=evaluation.pk,
                actor=None,
                institute=attempt.exam.institute,
            )
    for question in attempt.exam.paper.paper_questions.filter(question_type='coding'):
        answer = ExamAnswer.objects.select_for_update().filter(
            attempt=attempt, paper_question=question
        ).first()
        if answer is not None:
            continue
        answer = ExamAnswer.objects.create(
            attempt=attempt,
            paper_question=question,
            response={'code': '', 'language': ''},
        )
        evaluation, created = ExamAnswerEvaluation.objects.get_or_create(
            answer=answer,
            defaults={
                'status': EvaluationStatus.GRADED,
                'marks_awarded': Decimal('0.00'),
                'max_marks': question.marks,
                'grading_method': 'code_execution',
                'evaluated_at': timezone.now(),
                'details': {'reason': 'no_submission'},
            },
        )
        if created:
            record_audit_event(
                action='answer.evaluated',
                resource_type='exam_answer_evaluation',
                resource_id=evaluation.pk,
                actor=None,
                institute=attempt.exam.institute,
            )
    for question in attempt.exam.paper.paper_questions.filter(question_type='coding'):
        answer = ExamAnswer.objects.select_for_update().filter(
            attempt=attempt, paper_question=question
        ).first()
        if answer is not None:
            continue
        answer = ExamAnswer.objects.create(
            attempt=attempt,
            paper_question=question,
            response={'code': '', 'language': ''},
        )
        evaluation, created = ExamAnswerEvaluation.objects.get_or_create(
            answer=answer,
            defaults={
                'status': EvaluationStatus.GRADED,
                'marks_awarded': Decimal('0.00'),
                'max_marks': question.marks,
                'grading_method': 'code_execution',
                'evaluated_at': timezone.now(),
                'details': {'reason': 'no_submission'},
            },
        )
        if created:
            record_audit_event(
                action='answer.evaluated',
                resource_type='exam_answer_evaluation',
                resource_id=evaluation.pk,
                actor=None,
                institute=attempt.exam.institute,
            )


def create_coding_submission(*, attempt, user, question_id, code, language):
    submission = _create_coding_submission_locked(
        attempt=attempt,
        user=user,
        question_id=question_id,
        code=code,
        language=language,
    )
    if submission is None:
        raise APIValidationError({'detail': 'The exam deadline has passed; the attempt was auto-submitted.'})
    return submission


@transaction.atomic
def _create_coding_submission_locked(*, attempt, user, question_id, code, language):
    from .services import ensure_attempt_writable

    attempt = ExamAttempt.objects.select_for_update().select_related(
        'exam__paper', 'exam__institute'
    ).get(pk=attempt.pk)
    if not ensure_attempt_writable(attempt):
        return None
    if attempt.status != ExamAttemptStatus.IN_PROGRESS:
        raise APIValidationError({'detail': 'Coding submissions are accepted only during an active attempt.'})
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_LENGTH:
        raise APIValidationError({'code': f'Code must contain 1 to {MAX_CODE_LENGTH} characters.'})
    if not isinstance(language, str) or not language.strip() or len(language) > 50:
        raise APIValidationError({'language': 'A programming language is required (maximum 50 characters).'})
    question = attempt.exam.paper.paper_questions.filter(
        pk=question_id, question_type='coding'
    ).first()
    if question is None:
        raise APIValidationError({'question': 'A coding question from this exam is required.'})
    metadata = question.code_metadata_snapshot
    metadata = metadata if isinstance(metadata, dict) else {}
    allowed_languages = metadata.get('supported_languages') or metadata.get('languages')
    if not allowed_languages and isinstance(metadata.get('language'), str):
        allowed_languages = [metadata['language']]
    if (
        not isinstance(allowed_languages, list)
        or not allowed_languages
        or any(not isinstance(item, str) or not item for item in allowed_languages)
    ):
        raise APIValidationError({'question': 'This coding question has no valid supported-language configuration.'})
    if language not in allowed_languages:
        raise APIValidationError({'language': 'This language is not enabled for the coding question.'})
    answer, _ = ExamAnswer.objects.get_or_create(
        attempt=attempt, paper_question=question, defaults={'response': {'code': code, 'language': language}}
    )
    if answer.response != {'code': code, 'language': language}:
        answer.response = {'code': code, 'language': language}
        answer.revision += 1
        answer.save(update_fields=['response', 'revision', 'updated_at'])
    source_hash = hashlib.sha256(
        f'{language}\0{code}'.encode('utf-8')
    ).hexdigest()
    submission, created = CodingSubmission.objects.get_or_create(
        answer=answer,
        source_hash=source_hash,
        defaults={'code': code, 'language': language},
    )
    if created:
        record_audit_event(
            action='coding_submission.created',
            resource_type='coding_submission',
            resource_id=submission.pk,
            actor=user,
            institute=attempt.exam.institute,
        )
    return submission


def execute_coding_submission(submission, *, provider=None, actor=None, allow_submitted=False):
    provider = provider or CodeExecutionProvider()
    deadline_passed = False
    already_completed = False
    with transaction.atomic():
        submission = CodingSubmission.objects.select_for_update().select_related(
            'answer__paper_question', 'answer__attempt__exam'
        ).get(pk=submission.pk)
        from .services import ensure_attempt_writable

        attempt = submission.answer.attempt
        attempt_already_submitted = (
            allow_submitted
            and attempt.status in (ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED)
        )
        if not attempt_already_submitted and not ensure_attempt_writable(attempt):
            deadline_passed = True
        if not deadline_passed:
            if submission.status == CodingSubmissionStatus.COMPLETED:
                already_completed = True
            elif submission.status == CodingSubmissionStatus.RUNNING:
                raise APIValidationError({'detail': 'This coding submission is already being evaluated.'})
            else:
                question = submission.answer.paper_question
                test_cases = question.test_cases_snapshot
                if not isinstance(test_cases, list) or not test_cases:
                    raise APIValidationError({'detail': 'This coding question has no configured test cases.'})
                if len(test_cases) > 100:
                    raise APIValidationError({'detail': 'A coding question may contain at most 100 test cases.'})
                for case in test_cases:
                    if (
                        not isinstance(case, dict)
                        or not isinstance(case.get('input'), str)
                        or not isinstance(case.get('expected_output'), str)
                        or len(case['input']) > 10_000
                        or len(case['expected_output']) > 10_000
                        or ('is_hidden' in case and not isinstance(case['is_hidden'], bool))
                    ):
                        raise APIValidationError({'detail': 'The coding question contains an invalid test-case snapshot.'})
                metadata = question.code_metadata_snapshot
                metadata = metadata if isinstance(metadata, dict) else {}
                constraints = metadata.get('execution_constraints')
                constraints = constraints if isinstance(constraints, dict) else {}
                time_limit = constraints.get('time_limit_seconds', 3)
                memory_limit = constraints.get('memory_limit_mb', 128)
                if (
                    not isinstance(time_limit, int) or isinstance(time_limit, bool)
                    or not isinstance(memory_limit, int) or isinstance(memory_limit, bool)
                ):
                    raise APIValidationError({'detail': 'Coding execution limits are invalid.'})
                time_limit = min(max(time_limit, 1), 15)
                memory_limit = min(max(memory_limit, 32), 512)
                submission.status = CodingSubmissionStatus.RUNNING
                submission.save(update_fields=['status'])

    if deadline_passed:
        raise APIValidationError({'detail': 'The exam deadline has passed; the attempt was auto-submitted.'})
    if already_completed:
        return submission

    try:
        passed = provider.execute(
            code=submission.code,
            language=submission.language,
            test_cases=test_cases,
            time_limit_seconds=time_limit,
            memory_limit_mb=memory_limit,
        )
    except ProviderConfigurationError:
        with transaction.atomic():
            submission.status = CodingSubmissionStatus.QUEUED
            submission.error_code = 'provider_not_configured'
            submission.save(update_fields=['status', 'error_code'])
        raise
    except ProviderExecutionError:
        with transaction.atomic():
            submission.status = CodingSubmissionStatus.FAILED
            submission.error_code = 'provider_error'
            submission.completed_at = timezone.now()
            submission.save(update_fields=['status', 'error_code', 'completed_at'])
            record_audit_event(
                action='coding_submission.evaluation_failed',
                resource_type='coding_submission',
                resource_id=submission.pk,
                actor=None,
                institute=submission.answer.attempt.exam.institute,
                outcome='failed',
            )
        raise

    passed_count = sum(passed)
    marks_awarded = (
        question.marks * Decimal(passed_count) / Decimal(len(test_cases))
    ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    with transaction.atomic():
        submission = CodingSubmission.objects.select_for_update().get(pk=submission.pk)
        submission.status = CodingSubmissionStatus.COMPLETED
        submission.test_results = passed
        submission.passed_count = passed_count
        submission.total_count = len(test_cases)
        submission.marks_awarded = marks_awarded
        submission.error_code = ''
        submission.completed_at = timezone.now()
        submission.save(update_fields=[
            'status', 'test_results', 'passed_count', 'total_count', 'marks_awarded',
            'error_code', 'completed_at',
        ])
        ExamAnswerEvaluation.objects.update_or_create(
            answer=submission.answer,
            defaults={
                'status': EvaluationStatus.GRADED,
                'marks_awarded': marks_awarded,
                'max_marks': question.marks,
                'grading_method': 'code_execution',
                'evaluated_at': timezone.now(),
                'details': {
                    'passed_count': passed_count,
                    'total_count': len(test_cases),
                },
            },
        )
        record_audit_event(
            action='coding_submission.evaluated',
            resource_type='coding_submission',
            resource_id=submission.pk,
            actor=actor,
            institute=submission.answer.attempt.exam.institute,
        )
    return submission


def extract_handwritten_sheet(sheet, *, provider=None):
    provider = provider or OCRProvider()
    if sheet.status in (HandwrittenSheetStatus.HUMAN_REVIEW, HandwrittenSheetStatus.REVIEWED):
        raise APIValidationError({'detail': 'This sheet has already been extracted or reviewed.'})
    if sheet.file.size > MAX_HANDWRITTEN_FILE_BYTES:
        raise APIValidationError({'file': 'Answer sheet exceeds the 20 MB limit.'})
    extension = sheet.file.name.rsplit('.', 1)[-1].lower()
    if extension not in ALLOWED_HANDWRITTEN_EXTENSIONS:
        raise APIValidationError({'file': 'Only PDF, PNG, and JPEG answer sheets are supported.'})
    content_types = {
        'pdf': 'application/pdf',
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
    }
    sheet.file.open('rb')
    try:
        file_bytes = sheet.file.read(MAX_HANDWRITTEN_FILE_BYTES + 1)
    finally:
        sheet.file.close()
    if len(file_bytes) > MAX_HANDWRITTEN_FILE_BYTES:
        raise APIValidationError({'file': 'Answer sheet exceeds the 20 MB limit.'})
    try:
        text = provider.extract_text(
            file_bytes=file_bytes,
            filename=sheet.file.name.rsplit('/', 1)[-1],
            content_type=content_types[extension],
        )
    except ProviderConfigurationError:
        raise
    except ProviderExecutionError:
        sheet.status = HandwrittenSheetStatus.EXTRACTION_FAILED
        sheet.extraction_error = 'ocr_provider_error'
        sheet.save(update_fields=['status', 'extraction_error'])
        raise
    sheet.extracted_text = text
    sheet.status = HandwrittenSheetStatus.HUMAN_REVIEW
    sheet.extraction_error = ''
    sheet.extracted_at = timezone.now()
    sheet.save(update_fields=['extracted_text', 'status', 'extraction_error', 'extracted_at'])
    return sheet


@transaction.atomic
def review_handwritten_sheet(sheet, reviewer, evaluations):
    sheet = HandwrittenAnswerSheet.objects.select_for_update().select_related(
        'attempt__exam'
    ).get(pk=sheet.pk)
    if sheet.status == HandwrittenSheetStatus.REVIEWED:
        raise APIValidationError({'detail': 'This answer sheet has already been reviewed.'})
    questions = {
        str(question.pk): question
        for question in sheet.attempt.exam.paper.paper_questions.all()
    }
    submitted_ids = set()
    for item in evaluations:
        question_id = str(item['question'])
        question = questions.get(question_id)
        if question is None or question.question_type not in ('short_answer', 'long_answer'):
            raise APIValidationError({'evaluations': 'Every question must be a subjective question on this paper.'})
        if question_id in submitted_ids:
            raise APIValidationError({'evaluations': 'A question may be graded only once per review.'})
        submitted_ids.add(question_id)
        marks = Decimal(str(item['marks_awarded']))
        if marks < 0 or marks > question.marks:
            raise APIValidationError({'evaluations': f'Marks for question {question.question_number} are out of range.'})
        rubric = question.rubric_snapshot or []
        if not rubric:
            raise APIValidationError({
                'evaluations': f'Question {question.question_number} has no released rubric and cannot be graded.'
            })
        rubric_scores = item.get('rubric_scores', {})
        if not isinstance(rubric_scores, dict):
            raise APIValidationError({'evaluations': 'Rubric scores must be an object.'})
        criterion_names = {
            criterion.get('criterion'): Decimal(str(criterion.get('max_marks', '0')))
            for criterion in rubric if isinstance(criterion, dict)
        }
        if len(criterion_names) != len(rubric):
            raise APIValidationError({'evaluations': 'The released rubric contains duplicate or invalid criteria.'})
        if sum(criterion_names.values(), Decimal('0.00')) != question.marks:
            raise APIValidationError({
                'evaluations': f'The released rubric for question {question.question_number} does not reconcile to its marks.'
            })
        if set(rubric_scores) - set(criterion_names):
            raise APIValidationError({'evaluations': 'Rubric scores contain an unknown criterion.'})
        if criterion_names and set(rubric_scores) != set(criterion_names):
            raise APIValidationError({'evaluations': 'Provide a score for every rubric criterion.'})
        rubric_total = Decimal('0.00')
        for criterion, score in rubric_scores.items():
            score_value = Decimal(str(score))
            if score_value < 0 or score_value > criterion_names[criterion]:
                raise APIValidationError({'evaluations': f'Rubric score for {criterion} is out of range.'})
            rubric_total += score_value
        if criterion_names and rubric_total != marks:
            raise APIValidationError({'evaluations': 'Awarded marks must equal the rubric score total.'})
        review, _ = HandwrittenAnswerEvaluation.objects.update_or_create(
            sheet=sheet,
            paper_question=question,
            defaults={
                'marks_awarded': marks,
                'max_marks': question.marks,
                'rubric_scores': {
                    criterion: str(score) for criterion, score in rubric_scores.items()
                },
                'feedback': item.get('feedback', ''),
                'reviewed_by': reviewer,
            },
        )
        review.full_clean()
        review.save()
    sheet.status = HandwrittenSheetStatus.REVIEWED
    sheet.save(update_fields=['status'])
    record_audit_event(
        action='handwritten_sheet.reviewed',
        resource_type='handwritten_answer_sheet',
        resource_id=sheet.pk,
        actor=reviewer,
        institute=sheet.attempt.exam.institute,
    )
    return sheet
