from django.db.models import Q
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from decimal import Decimal
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import FileResponse
from drf_spectacular.utils import extend_schema

from apps.accounts.models import MembershipStatus, RoleChoices
from apps.accounts.permissions import EnforcePasswordChange
from apps.academics.models import StudentAcademicPlacement, PlacementStatus

from .models import (
    ExamActivityEvent,
    ExamActivitySource,
    ExamActivityType,
    ExamAttempt,
    ExamAttemptStatus,
    ExamIntegrityFlag,
    ExamSchedule,
    ExamScheduleStatus,
    CodingSubmission,
    CodingSubmissionStatus,
    HandwrittenAnswerSheet,
    HandwrittenSheetStatus,
    ExamGrievance,
    RevaluationRequestStatus,
    RevaluationRequest,
)
from .permissions import is_exam_manager
from .serializers import (
    AnswerWriteSerializer,
    AttemptSerializer,
    ClientActivityEventSerializer,
    DeliveredPaperQuestionSerializer,
    ExamActivityEventSerializer,
    ExamAnswerSerializer,
    ExamScheduleSerializer,
    ExamStudentSerializer,
    IntegrityFlagReviewSerializer,
    IntegrityFlagSerializer,
    CodingSubmissionSerializer,
    CodingSubmissionWriteSerializer,
    ExamResultSerializer,
    HandwrittenAnswerSheetSerializer,
    HandwrittenAnswerSheetUploadSerializer,
    HandwrittenReviewSerializer,
    RevaluationDecisionSerializer,
    RevaluationRequestCreateSerializer,
    RevaluationRequestSerializer,
    ExamGrievanceCreateSerializer,
    ExamGrievanceDecisionSerializer,
    ExamGrievanceSerializer,
)
from .services import (
    eligible_placements,
    ensure_attempt_writable,
    get_owned_attempt,
    report_client_event,
    review_integrity_flag,
    save_answer,
    start_or_resume_exam,
    submit_attempt,
)
from .evaluation_services import (
    create_coding_submission,
    execute_coding_submission,
    extract_handwritten_sheet,
    review_handwritten_sheet,
)
from .provider_services import ProviderConfigurationError, ProviderExecutionError
from .revaluation_services import (
    decide_exam_grievance,
    decide_revaluation,
    submit_exam_grievance,
    submit_revaluation_request,
)


class ProviderUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'The required external provider is not configured.'
    default_code = 'provider_unavailable'


class ProviderBadGateway(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = 'The configured external provider failed.'
    default_code = 'provider_error'


def _result_for_attempt(attempt):
    sheet = getattr(attempt, 'handwritten_sheet', None)
    handwritten = {}
    if sheet and sheet.status == HandwrittenSheetStatus.REVIEWED:
        handwritten = {
            item.paper_question_id: item
            for item in sheet.evaluations.all()
        }
    questions = []
    total = 0
    maximum = 0
    final = True
    answers = {
        item.paper_question_id: item
        for item in attempt.answers.all()
    }
    revaluations = {
        item.paper_question_id: item
        for item in attempt.revaluation_requests.all()
        if item.status == RevaluationRequestStatus.APPROVED and item.corrected_marks is not None
    }
    for question in attempt.exam.paper.paper_questions.all():
        max_marks = question.marks
        maximum += max_marks
        human_grade = handwritten.get(question.id)
        answer = answers.get(question.id)
        evaluation = getattr(answer, 'evaluation', None) if answer else None
        if human_grade:
            awarded = human_grade.marks_awarded
            state = 'graded'
            feedback = human_grade.feedback
        elif evaluation and evaluation.status == 'graded':
            awarded = evaluation.marks_awarded or Decimal('0.00')
            state = evaluation.status
            feedback = evaluation.feedback
        else:
            awarded = Decimal('0.00')
            state = evaluation.status if evaluation else 'pending'
            feedback = ''
            final = False
        revaluation = revaluations.get(question.id)
        if revaluation is not None:
            awarded = revaluation.corrected_marks
            state = 'graded'
        total += awarded
        questions.append({
            'question': question.id,
            'question_number': question.question_number,
            'marks_awarded': awarded,
            'max_marks': max_marks,
            'status': state,
            'feedback': feedback,
        })
    if sheet and sheet.status != HandwrittenSheetStatus.REVIEWED:
        final = False
    return {
        'attempt': attempt.id,
        'status': attempt.status,
        'marks_awarded': total,
        'max_marks': maximum,
        'is_final': final,
        'questions': questions,
    }


class ExamScheduleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    filterset_fields = ['status', 'published']
    search_fields = ['paper__title', 'paper__subject__code', 'batch__name']
    ordering_fields = ['starts_at', 'created_at']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy', 'publish', 'cancel'}:
            return [IsAuthenticated(), EnforcePasswordChange()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        if getattr(self, 'swagger_fake_view', False) or not user or not user.is_authenticated:
            return ExamSchedule.objects.none()
        schedules = ExamSchedule.objects.select_related(
            'institute', 'paper__subject', 'paper__blueprint', 'batch', 'section', 'created_by'
        )
        if user.is_platform_admin:
            return schedules
        manager_institutes = [
            membership.institute_id for membership in user.memberships.filter(
                status=MembershipStatus.ACTIVE,
                role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            )
            if membership.role == RoleChoices.INSTITUTE_ADMIN
            or {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
        ]
        is_student = user.memberships.filter(
            role=RoleChoices.STUDENT, status=MembershipStatus.ACTIVE
        ).exists()
        if self.action in {'list', 'retrieve', 'instructions', 'start', 'questions', 'my_attempt', 'history'} and is_student:
            placement_ids = StudentAcademicPlacement.objects.filter(
                student__user=user,
                student__role=RoleChoices.STUDENT,
                student__status=MembershipStatus.ACTIVE,
                status=PlacementStatus.ACTIVE,
                effective_start_date__lte=timezone.localdate(),
            ).filter(
                Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=timezone.localdate())
            ).values_list('id', flat=True)
            current_student_schedules = schedules.filter(
                published=True,
                status=ExamScheduleStatus.SCHEDULED,
                batch__student_placements__in=placement_ids,
            ).filter(Q(section__isnull=True) | Q(section__student_placements__in=placement_ids))
            current_student_schedules = current_student_schedules.filter(
                ends_at__gt=timezone.now()
            )
            eligible_ids = [
                exam.id for exam in current_student_schedules.distinct()
                if eligible_placements(exam, user).exists()
            ]
            student_schedules = current_student_schedules.filter(id__in=eligible_ids).distinct()
            if self.action in {'history', 'my_attempt'}:
                history_schedules = schedules.filter(
                    published=True,
                    status=ExamScheduleStatus.SCHEDULED,
                    attempts__placement__student__user=user,
                    attempts__placement__student__status=MembershipStatus.ACTIVE,
                    attempts__placement__student__role=RoleChoices.STUDENT,
                ).distinct()
                student_schedules = student_schedules | history_schedules
            if manager_institutes:
                return (student_schedules | schedules.filter(institute_id__in=manager_institutes)).distinct()
            return student_schedules.distinct()
        return schedules.filter(institute_id__in=manager_institutes).distinct()

    def get_serializer_class(self):
        student_facing_actions = {'list', 'retrieve', 'instructions', 'start', 'questions', 'my_attempt', 'history'}
        if self.action not in student_facing_actions:
            return ExamScheduleSerializer
        user = getattr(self.request, 'user', None)
        if getattr(self, 'swagger_fake_view', False) or not user or not user.is_authenticated:
            return ExamScheduleSerializer
        if self.action == 'list':
            has_student_role = user.memberships.filter(
                role=RoleChoices.STUDENT, status=MembershipStatus.ACTIVE
            ).exists()
            has_manager_role = user.is_platform_admin or any(
                membership.role == RoleChoices.INSTITUTE_ADMIN
                or {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
                for membership in user.memberships.filter(
                    status=MembershipStatus.ACTIVE,
                    role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
                )
            )
            return ExamScheduleSerializer if has_manager_role and not has_student_role else ExamStudentSerializer
        institute_id = self.request.data.get('institute')
        if not institute_id and self.kwargs.get('pk'):
            institute_id = ExamSchedule.objects.filter(pk=self.kwargs['pk']).values_list(
                'institute_id', flat=True
            ).first()
        if is_exam_manager(user, institute_id):
            return ExamScheduleSerializer
        return ExamStudentSerializer

    def _require_manager(self, exam):
        if not is_exam_manager(self.request.user, exam.institute_id):
            raise PermissionDenied('Exam management permission is required for this institute.')

    @transaction.atomic
    def perform_create(self, serializer):
        institute = serializer.validated_data['institute']
        if not is_exam_manager(self.request.user, institute.id):
            raise PermissionDenied('Exam management permission is required for this institute.')
        exam = serializer.save(created_by=self.request.user)
        ExamActivityEvent.objects.create(
            institute=exam.institute,
            exam=exam,
            actor=self.request.user,
            event_type=ExamActivityType.SCHEDULE_CREATED,
            source=ExamActivitySource.SERVER_VERIFIED,
        )
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='exam.schedule.created',
            resource_type='exam_schedule',
            resource_id=exam.pk,
            actor=self.request.user,
            institute=exam.institute,
        )

    @transaction.atomic
    def perform_update(self, serializer):
        exam = self.get_object()
        self._require_manager(exam)
        target_institute = serializer.validated_data.get('institute', exam.institute)
        if not is_exam_manager(self.request.user, target_institute.id):
            raise PermissionDenied('Exam management permission is required for the target institute.')
        if exam.attempts.exists():
            raise ValidationError('Exam schedules cannot be changed after an attempt has started.')
        exam = serializer.save()
        ExamActivityEvent.objects.create(
            institute=exam.institute,
            exam=exam,
            actor=self.request.user,
            event_type=ExamActivityType.SCHEDULE_UPDATED,
            source=ExamActivitySource.SERVER_VERIFIED,
        )
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='exam.schedule.updated',
            resource_type='exam_schedule',
            resource_id=exam.pk,
            actor=self.request.user,
            institute=exam.institute,
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        self._require_manager(instance)
        if instance.attempts.exists():
            raise ValidationError('Exam schedules with attempts cannot be deleted; cancel the exam instead.')
        ExamActivityEvent.objects.create(
            institute=instance.institute,
            exam=instance,
            actor=self.request.user,
            event_type=ExamActivityType.SCHEDULE_DELETED,
            source=ExamActivitySource.SERVER_VERIFIED,
        )
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='exam.schedule.deleted',
            resource_type='exam_schedule',
            resource_id=instance.pk,
            actor=self.request.user,
            institute=instance.institute,
        )
        instance.delete()

    @extend_schema(summary='Get exam instructions and eligibility')
    @action(detail=True, methods=['get'], url_path='instructions')
    def instructions(self, request, pk=None):
        exam = self.get_object()
        if not eligible_placements(exam, request.user).exists():
            raise PermissionDenied('You are not eligible to access this exam.')
        if not exam.published or exam.status != ExamScheduleStatus.SCHEDULED:
            raise NotFound('Exam not found.')
        return Response({
            'exam_id': str(exam.id),
            'paper_title': exam.paper.title,
            'subject': exam.paper.subject.name,
            'starts_at': exam.starts_at,
            'ends_at': exam.ends_at,
            'duration_minutes': exam.paper.duration_minutes,
            'instructions': exam.instructions,
        })

    @extend_schema(summary='Start or resume an eligible exam attempt', responses={200: AttemptSerializer})
    @action(detail=True, methods=['post'], url_path='start')
    def start(self, request, pk=None):
        exam = self.get_object()
        attempt = start_or_resume_exam(exam.id, request.user)
        return Response(AttemptSerializer(attempt).data, status=status.HTTP_200_OK)

    @extend_schema(summary='Deliver the authorized exam questions')
    @action(detail=True, methods=['get'], url_path='questions')
    def questions(self, request, pk=None):
        exam = self.get_object()
        attempt = ExamAttempt.objects.filter(
            exam=exam,
            placement__student__user=request.user,
            placement__student__status=MembershipStatus.ACTIVE,
        ).exclude(status__in=[
            ExamAttemptStatus.SUBMITTED,
            ExamAttemptStatus.AUTO_SUBMITTED,
            ExamAttemptStatus.EXPIRED,
            ExamAttemptStatus.CANCELLED,
        ]).select_related('exam__paper').first()
        if not attempt:
            raise NotFound('No active exam attempt was found.')
        if not ensure_attempt_writable(attempt):
            raise ValidationError('The exam deadline has passed; the attempt was auto-submitted.')
        questions = exam.paper.paper_questions.all()
        return Response(DeliveredPaperQuestionSerializer(questions, many=True).data)

    @extend_schema(summary='Get the authenticated student’s current attempt for this exam')
    @action(detail=True, methods=['get'], url_path='my-attempt')
    def my_attempt(self, request, pk=None):
        exam = self.get_object()
        attempt = ExamAttempt.objects.filter(
            exam=exam,
            placement__student__user=request.user,
            placement__student__status=MembershipStatus.ACTIVE,
        ).select_related('exam__paper').order_by('-started_at').first()
        if not attempt:
            return Response({'attempt': None})
        return Response({'attempt': AttemptSerializer(attempt).data})

    @extend_schema(summary='List the authenticated student’s attempt history')
    @action(detail=True, methods=['get'], url_path='history')
    def history(self, request, pk=None):
        exam = self.get_object()
        attempts = ExamAttempt.objects.filter(
            exam=exam,
            placement__student__user=request.user,
            placement__student__status=MembershipStatus.ACTIVE,
        ).select_related('exam__paper')
        return Response(AttemptSerializer(attempts, many=True).data)

    @transaction.atomic
    @extend_schema(summary='Publish exam to eligible students')
    @action(detail=True, methods=['post'], url_path='publish')
    def publish(self, request, pk=None):
        exam = ExamSchedule.objects.select_for_update().select_related('institute').get(
            pk=self.get_object().pk
        )
        self._require_manager(exam)
        if exam.status != ExamScheduleStatus.SCHEDULED:
            raise ValidationError('Only scheduled exams can be published.')
        if exam.published:
            raise ValidationError('This exam has already been published.')
        if exam.attempts.exists():
            raise ValidationError('An exam cannot be republished after attempts exist.')
        exam.published = True
        exam.save(update_fields=['published', 'updated_at'])
        ExamActivityEvent.objects.create(
            institute=exam.institute,
            exam=exam,
            actor=request.user,
            event_type=ExamActivityType.SCHEDULE_PUBLISHED,
            source=ExamActivitySource.SERVER_VERIFIED,
        )
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='exam.schedule.published',
            resource_type='exam_schedule',
            resource_id=exam.pk,
            actor=request.user,
            institute=exam.institute,
        )
        return Response(ExamScheduleSerializer(exam).data)

    @transaction.atomic
    @extend_schema(summary='Cancel an exam schedule')
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        exam = ExamSchedule.objects.select_for_update().select_related('institute').get(
            pk=self.get_object().pk
        )
        self._require_manager(exam)
        if exam.status == ExamScheduleStatus.CANCELLED:
            raise ValidationError('This exam has already been cancelled.')
        if exam.attempts.filter(status=ExamAttemptStatus.IN_PROGRESS).exists():
            raise ValidationError('An exam with in-progress attempts cannot be cancelled.')
        exam.status = ExamScheduleStatus.CANCELLED
        exam.save(update_fields=['status', 'updated_at'])
        ExamActivityEvent.objects.create(
            institute=exam.institute,
            exam=exam,
            actor=request.user,
            event_type=ExamActivityType.SCHEDULE_CANCELLED,
            source=ExamActivitySource.SERVER_VERIFIED,
        )
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='exam.schedule.cancelled',
            resource_type='exam_schedule',
            resource_id=exam.pk,
            actor=request.user,
            institute=exam.institute,
        )
        return Response(ExamScheduleSerializer(exam).data)

    @extend_schema(summary='View exam activity (exam managers only)')
    @action(detail=True, methods=['get'], url_path='activity')
    def activity(self, request, pk=None):
        exam = self.get_object()
        if not is_exam_manager(request.user, exam.institute_id):
            raise PermissionDenied('Exam management permission is required for this institute.')
        events = exam.activity_events.select_related('actor').all()
        return Response(ExamActivityEventSerializer(events, many=True).data)


class ExamAttemptViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]
    serializer_class = AttemptSerializer
    queryset = ExamAttempt.objects.none()

    def get_queryset(self):
        user = self.request.user
        attempts = ExamAttempt.objects.select_related(
            'exam__institute', 'exam__paper', 'placement__student__user'
        )
        if not user.is_authenticated:
            return attempts.none()
        return attempts.filter(
            placement__student__user=user,
            placement__student__status=MembershipStatus.ACTIVE,
            placement__student__role=RoleChoices.STUDENT,
            placement__status=PlacementStatus.ACTIVE,
        )

    def _own_attempt(self, pk):
        return get_owned_attempt(pk, self.request.user)

    @extend_schema(summary='Retrieve the student’s saved answers for an attempt')
    @action(detail=True, methods=['get', 'put'], url_path='answers')
    def answers(self, request, pk=None):
        attempt = self._own_attempt(pk)
        if request.method == 'PUT':
            serializer = AnswerWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            answer = save_answer(
                attempt.id,
                request.user,
                serializer.validated_data['question'],
                serializer.validated_data['response'],
            )
            return Response(ExamAnswerSerializer(answer).data, status=status.HTTP_200_OK)
        if attempt.status == ExamAttemptStatus.IN_PROGRESS:
            if not ensure_attempt_writable(attempt):
                raise ValidationError('The exam deadline has passed; the attempt was auto-submitted.')
        answers = attempt.answers.select_related('paper_question').all()
        return Response(ExamAnswerSerializer(answers, many=True).data)

    @extend_schema(summary='Submit an exam attempt')
    @action(detail=True, methods=['post'], url_path='submit')
    def submit(self, request, pk=None):
        attempt = submit_attempt(pk, request.user)
        return Response(AttemptSerializer(attempt).data)

    @extend_schema(summary='Submit code for an exam coding question')
    @action(detail=True, methods=['post'], url_path='coding-submissions')
    def coding_submissions(self, request, pk=None):
        attempt = self._own_attempt(pk)
        if not ensure_attempt_writable(attempt):
            raise ValidationError('The exam deadline has passed; the attempt was auto-submitted.')
        serializer = CodingSubmissionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission = create_coding_submission(
            attempt=attempt,
            user=request.user,
            question_id=serializer.validated_data['question'],
            code=serializer.validated_data['code'],
            language=serializer.validated_data['language'],
        )
        response_status = status.HTTP_201_CREATED if submission.status == CodingSubmissionStatus.QUEUED else status.HTTP_200_OK
        return Response(CodingSubmissionSerializer(submission).data, status=response_status)

    @extend_schema(summary='View the authenticated student’s result or an institute result')
    @action(detail=True, methods=['get'], url_path='result', serializer_class=ExamResultSerializer)
    def result(self, request, pk=None):
        attempt = ExamAttempt.objects.filter(pk=pk).select_related(
            'exam__institute', 'exam__paper', 'placement__student__user'
        ).first()
        if attempt is None:
            raise NotFound('Attempt not found.')
        owner = attempt.placement.student.user_id == request.user.id
        if not owner and not is_exam_manager(request.user, attempt.exam.institute_id):
            raise NotFound('Attempt not found.')
        if attempt.status not in (ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED):
            raise ValidationError('Results are available only after an attempt has been submitted.')
        payload = _result_for_attempt(attempt)
        return Response(ExamResultSerializer(payload).data)

    @extend_schema(summary='Report a permitted client-side integrity event')
    @action(detail=True, methods=['post'], url_path='events')
    def events(self, request, pk=None):
        serializer = ClientActivityEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recorded = report_client_event(
            pk,
            request.user,
            serializer.validated_data['event_type'],
            serializer.validated_data.get('metadata', {}),
        )
        if not recorded:
            raise ValidationError('The exam deadline has passed; the attempt was auto-submitted.')
        return Response({'recorded': True}, status=status.HTTP_201_CREATED)

    @extend_schema(summary='View attempt activity and integrity flags (exam managers only)')
    @action(detail=True, methods=['get'], url_path='activity')
    def activity(self, request, pk=None):
        if request.user.is_platform_admin:
            attempts = ExamAttempt.objects.all()
        else:
            managed_institutes = [
                membership.institute_id for membership in request.user.memberships.filter(
                    status=MembershipStatus.ACTIVE,
                    role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
                )
                if membership.role == RoleChoices.INSTITUTE_ADMIN
                or {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
            ]
            attempts = ExamAttempt.objects.filter(exam__institute_id__in=managed_institutes)
        attempt = attempts.filter(pk=pk).select_related('exam').first()
        if not attempt:
            raise NotFound('Attempt not found.')
        events = attempt.activity_events.all()
        flags = attempt.integrity_flags.all()
        return Response({
            'events': ExamActivityEventSerializer(events, many=True).data,
            'integrity_flags': IntegrityFlagSerializer(flags, many=True).data,
        })


class CodingSubmissionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]
    serializer_class = CodingSubmissionSerializer
    queryset = CodingSubmission.objects.none()

    def get_queryset(self):
        submissions = CodingSubmission.objects.select_related(
            'answer__paper_question', 'answer__attempt__exam__institute',
            'answer__attempt__placement__student__user',
        )
        user = self.request.user
        if not user.is_authenticated:
            return submissions.none()
        if user.is_platform_admin:
            return submissions
        own = submissions.filter(
            answer__attempt__placement__student__user=user,
            answer__attempt__placement__student__status=MembershipStatus.ACTIVE,
            answer__attempt__placement__status=PlacementStatus.ACTIVE,
        )
        managed_ids = [
            membership.institute_id for membership in user.memberships.filter(
                status=MembershipStatus.ACTIVE,
                role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            )
            if membership.role == RoleChoices.INSTITUTE_ADMIN
            or {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
        ]
        return (
            own | submissions.filter(answer__attempt__exam__institute_id__in=managed_ids)
        ).distinct()

    @extend_schema(summary='Run a submission using the configured isolated execution provider')
    @action(detail=True, methods=['post'], url_path='execute')
    def execute(self, request, pk=None):
        submission = self.get_object()
        attempt = submission.answer.attempt
        is_manager = is_exam_manager(request.user, attempt.exam.institute_id)
        is_owner = attempt.placement.student.user_id == request.user.id
        if not is_owner and not is_manager:
            raise NotFound('Submission not found.')
        if is_owner and not is_manager:
            attempt = get_owned_attempt(submission.answer.attempt_id, request.user)
            if not ensure_attempt_writable(attempt):
                raise ValidationError('The exam deadline has passed; the attempt was auto-submitted.')
        try:
            submission = execute_coding_submission(
                submission,
                actor=request.user,
                allow_submitted=is_manager,
            )
        except ProviderConfigurationError as exc:
            raise ProviderUnavailable(detail=str(exc), code='execution_provider_unavailable') from exc
        except ProviderExecutionError as exc:
            raise ProviderBadGateway(
                detail='The configured execution provider could not evaluate this submission.',
                code='execution_provider_error',
            ) from exc
        return Response(CodingSubmissionSerializer(submission).data)


class HandwrittenAnswerSheetViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]
    serializer_class = HandwrittenAnswerSheetSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = HandwrittenAnswerSheet.objects.none()

    def get_queryset(self):
        user = self.request.user
        sheets = HandwrittenAnswerSheet.objects.select_related(
            'attempt__exam__institute', 'attempt__placement__student__user'
        ).prefetch_related('evaluations__paper_question')
        if not user.is_authenticated:
            return sheets.none()
        if user.is_platform_admin:
            return sheets
        own = sheets.filter(attempt__placement__student__user=user)
        managed_ids = [
            membership.institute_id for membership in user.memberships.filter(
                status=MembershipStatus.ACTIVE,
                role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            )
            if membership.role == RoleChoices.INSTITUTE_ADMIN
            or {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
        ]
        return (own | sheets.filter(attempt__exam__institute_id__in=managed_ids)).distinct()

    @extend_schema(summary='Upload a handwritten answer sheet for a submitted exam attempt')
    def create(self, request, *args, **kwargs):
        serializer = HandwrittenAnswerSheetUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt = get_owned_attempt(serializer.validated_data['attempt'], request.user)
        if attempt.status not in (ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED):
            raise ValidationError('Answer sheets may be uploaded only for a submitted attempt.')
        if hasattr(attempt, 'handwritten_sheet'):
            raise ValidationError('An answer sheet has already been uploaded for this attempt.')
        sheet = HandwrittenAnswerSheet.objects.create(
            attempt=attempt,
            file=serializer.validated_data['file'],
            uploaded_by=request.user,
        )
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='handwritten_sheet.uploaded',
            resource_type='handwritten_answer_sheet',
            resource_id=sheet.pk,
            actor=request.user,
            institute=attempt.exam.institute,
        )
        return Response(
            HandwrittenAnswerSheetSerializer(sheet, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(summary='Extract text using the configured OCR provider')
    @action(detail=True, methods=['post'], url_path='extract')
    def extract(self, request, pk=None):
        sheet = self.get_object()
        if not is_exam_manager(request.user, sheet.attempt.exam.institute_id):
            raise PermissionDenied('Exam management permission is required for this institute.')
        try:
            sheet = extract_handwritten_sheet(sheet)
        except ProviderConfigurationError as exc:
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='handwritten_sheet.extraction_failed',
                resource_type='handwritten_answer_sheet',
                resource_id=sheet.pk,
                actor=request.user,
                institute=sheet.attempt.exam.institute,
                outcome='failed',
                metadata={'job_status': 'provider_not_configured'},
            )
            raise ProviderUnavailable(detail=str(exc), code='ocr_provider_unavailable') from exc
        except ProviderExecutionError as exc:
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='handwritten_sheet.extraction_failed',
                resource_type='handwritten_answer_sheet',
                resource_id=sheet.pk,
                actor=request.user,
                institute=sheet.attempt.exam.institute,
                outcome='failed',
                metadata={'job_status': 'provider_error'},
            )
            raise ProviderBadGateway(
                detail='The configured OCR provider could not extract this answer sheet.',
                code='ocr_provider_error',
            ) from exc
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='handwritten_sheet.extracted',
            resource_type='handwritten_answer_sheet',
            resource_id=sheet.pk,
            actor=request.user,
            institute=sheet.attempt.exam.institute,
            metadata={'job_status': sheet.status},
        )
        return Response(HandwrittenAnswerSheetSerializer(
            sheet, context=self.get_serializer_context()
        ).data)

    @extend_schema(summary='Download an authorized handwritten answer sheet')
    @action(detail=True, methods=['get'], url_path='download')
    def download(self, _request, pk=None):
        sheet = self.get_object()
        extension = sheet.file.name.rsplit('.', 1)[-1].lower()
        content_type = {
            'pdf': 'application/pdf',
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
        }.get(extension, 'application/octet-stream')
        response = FileResponse(
            sheet.file.open('rb'),
            as_attachment=True,
            filename=f'answer-sheet.{extension}',
            content_type=content_type,
        )
        response['Cache-Control'] = 'private, no-store'
        return response

    @extend_schema(summary='Apply a human rubric review to a handwritten answer sheet')
    @action(detail=True, methods=['post'], url_path='review')
    def review(self, request, pk=None):
        sheet = self.get_object()
        if not is_exam_manager(request.user, sheet.attempt.exam.institute_id):
            raise PermissionDenied('Exam management permission is required for this institute.')
        serializer = HandwrittenReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sheet = review_handwritten_sheet(
            sheet, request.user, serializer.validated_data['evaluations']
        )
        return Response(HandwrittenAnswerSheetSerializer(
            sheet, context=self.get_serializer_context()
        ).data)


class ExamIntegrityFlagViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]
    serializer_class = IntegrityFlagSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return ExamIntegrityFlag.objects.none()
        if user.is_platform_admin:
            return ExamIntegrityFlag.objects.select_related(
                'attempt__exam', 'attempt__placement__student__user', 'reviewed_by'
            )
        institute_ids = [
            membership.institute_id for membership in user.memberships.filter(
                status=MembershipStatus.ACTIVE,
                role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            )
            if membership.role == RoleChoices.INSTITUTE_ADMIN
            or {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
        ]
        return ExamIntegrityFlag.objects.filter(
            attempt__exam__institute_id__in=institute_ids
        ).select_related('attempt__exam', 'attempt__placement__student__user', 'reviewed_by')

    @extend_schema(summary='Review or dismiss an integrity flag')
    @action(detail=True, methods=['post'], url_path='review')
    def review(self, request, pk=None):
        flag = self.get_object()
        if not is_exam_manager(request.user, flag.attempt.exam.institute_id):
            raise PermissionDenied('Exam management permission is required for this institute.')
        serializer = IntegrityFlagReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        flag = review_integrity_flag(
            flag,
            request.user,
            serializer.validated_data['status'],
            serializer.validated_data['review_decision'],
        )
        return Response(IntegrityFlagSerializer(flag).data)


class RevaluationRequestViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]
    serializer_class = RevaluationRequestSerializer
    queryset = RevaluationRequest.objects.none()

    def get_queryset(self):
        user = self.request.user
        requests = RevaluationRequest.objects.select_related(
            'attempt__exam__institute', 'attempt__placement__student__user',
            'paper_question', 'reviewer',
        ).prefetch_related('decisions__reviewer')
        if not user.is_authenticated:
            return requests.none()
        if user.is_platform_admin:
            return requests
        managed_ids = [
            membership.institute_id for membership in user.memberships.filter(
                status=MembershipStatus.ACTIVE,
                role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            )
            if membership.role == RoleChoices.INSTITUTE_ADMIN
            or {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
        ]
        owned = requests.filter(attempt__placement__student__user=user)
        managed = requests.filter(attempt__exam__institute_id__in=managed_ids)
        return (owned | managed).distinct()

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = RevaluationRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt = ExamAttempt.objects.select_for_update().select_related(
            'exam__institute', 'exam__paper', 'placement__student__user'
        ).filter(
            pk=serializer.validated_data['attempt'],
            placement__student__user=request.user,
            placement__student__role=RoleChoices.STUDENT,
            placement__student__status=MembershipStatus.ACTIVE,
        ).first()
        if attempt is None:
            raise NotFound('Attempt not found.')
        if attempt.status not in (ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED):
            raise ValidationError({'attempt': 'Revaluation is available only after submission.'})
        result = _result_for_attempt(attempt)
        if not result['is_final']:
            raise ValidationError({'attempt': 'Revaluation is available only after the result is final.'})
        created = submit_revaluation_request(
            attempt_id=attempt.pk,
            question_id=serializer.validated_data['paper_question_id'],
            user=request.user,
            reason=serializer.validated_data['reason'],
        )
        return Response(
            RevaluationRequestSerializer(created, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(summary='Record an authorized revaluation decision and optional mark correction')
    @action(detail=True, methods=['post'], url_path='decide')
    def decide(self, request, pk=None):
        revaluation = self.get_object()
        if not is_exam_manager(request.user, revaluation.attempt.exam.institute_id):
            raise PermissionDenied('Exam management permission is required for this institute.')
        serializer = RevaluationDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        revaluation = decide_revaluation(
            revaluation.pk,
            request.user,
            **serializer.validated_data,
        )
        return Response(
            RevaluationRequestSerializer(revaluation, context=self.get_serializer_context()).data
        )


class ExamGrievanceViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]
    serializer_class = ExamGrievanceSerializer
    queryset = ExamGrievance.objects.none()

    def get_queryset(self):
        user = self.request.user
        grievances = ExamGrievance.objects.select_related(
            'attempt__exam__institute', 'attempt__placement__student__user',
            'filed_by', 'reviewer',
        ).prefetch_related('decisions__reviewer')
        if not user.is_authenticated:
            return grievances.none()
        if user.is_platform_admin:
            return grievances
        managed_ids = [
            membership.institute_id for membership in user.memberships.filter(
                status=MembershipStatus.ACTIVE,
                role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
            )
            if membership.role == RoleChoices.INSTITUTE_ADMIN
            or {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
        ]
        owned = grievances.filter(attempt__placement__student__user=user)
        managed = grievances.filter(attempt__exam__institute_id__in=managed_ids)
        return (owned | managed).distinct()

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = ExamGrievanceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt = ExamAttempt.objects.select_for_update().select_related(
            'exam__institute', 'exam__paper', 'placement__student__user'
        ).filter(
            pk=serializer.validated_data['attempt'],
            placement__student__user=request.user,
            placement__student__role=RoleChoices.STUDENT,
            placement__student__status=MembershipStatus.ACTIVE,
        ).first()
        if attempt is None:
            raise NotFound('Attempt not found.')
        if attempt.status not in (ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED):
            raise ValidationError({'attempt': 'A grievance can be filed only after submission.'})
        if not _result_for_attempt(attempt)['is_final']:
            raise ValidationError({'attempt': 'A grievance can be filed only after the result is final.'})
        grievance = submit_exam_grievance(
            attempt_id=attempt.pk,
            user=request.user,
            reason=serializer.validated_data['reason'],
        )
        return Response(
            ExamGrievanceSerializer(grievance, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(summary='Record an authorized grievance decision')
    @action(detail=True, methods=['post'], url_path='decide')
    def decide(self, request, pk=None):
        grievance = self.get_object()
        if not is_exam_manager(request.user, grievance.attempt.exam.institute_id):
            raise PermissionDenied('Exam management permission is required for this institute.')
        serializer = ExamGrievanceDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grievance = decide_exam_grievance(
            grievance.pk, request.user, **serializer.validated_data
        )
        return Response(
            ExamGrievanceSerializer(grievance, context=self.get_serializer_context()).data
        )


class ExamAnalyticsView(APIView):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]

    @extend_schema(
        summary='Retrieve institute, course, batch, or exam-level examination analytics',
        responses={200: dict},
    )
    def get(self, request):
        filters = ('institute', 'batch', 'subject', 'exam')
        if not any(request.query_params.get(name) for name in filters):
            raise ValidationError({
                'detail': 'Provide at least one of institute, batch, subject, or exam.'
            })
        validated_filters = {
            name: serializers.UUIDField().run_validation(request.query_params[name])
            for name in filters if request.query_params.get(name)
        }
        user = request.user
        schedules = ExamSchedule.objects.all()
        if not user.is_platform_admin:
            managed_ids = [
                membership.institute_id for membership in user.memberships.filter(
                    status=MembershipStatus.ACTIVE,
                    role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF],
                )
                if membership.role == RoleChoices.INSTITUTE_ADMIN
                or {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
            ]
            if not managed_ids:
                raise PermissionDenied('Examination analytics requires exam management permission.')
            schedules = schedules.filter(institute_id__in=managed_ids)
        if 'institute' in validated_filters:
            schedules = schedules.filter(institute_id=validated_filters['institute'])
        if 'batch' in validated_filters:
            schedules = schedules.filter(batch_id=validated_filters['batch'])
        if 'subject' in validated_filters:
            schedules = schedules.filter(paper__subject_id=validated_filters['subject'])
        if 'exam' in validated_filters:
            schedules = schedules.filter(pk=validated_filters['exam'])
        attempts = ExamAttempt.objects.select_related(
            'exam__paper', 'placement__student'
        ).prefetch_related(
            'exam__paper__paper_questions',
            'answers__evaluation',
            'handwritten_sheet__evaluations',
            'revaluation_requests',
        )
        schedules = schedules.select_related(
            'institute', 'paper__subject', 'batch'
        ).prefetch_related(Prefetch('attempts', queryset=attempts))
        results = []
        for exam in schedules:
            attempts_for_exam = list(exam.attempts.all())
            finalized = []
            pending = 0
            in_progress = 0
            other_attempts = 0
            for attempt in attempts_for_exam:
                if attempt.status == ExamAttemptStatus.IN_PROGRESS:
                    in_progress += 1
                    continue
                if attempt.status not in (
                    ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED
                ):
                    other_attempts += 1
                    continue
                result = _result_for_attempt(attempt)
                if result['is_final']:
                    finalized.append(result)
                else:
                    pending += 1

            total_marks = sum(
                (result['marks_awarded'] for result in finalized), Decimal('0.00')
            )
            question_stats = {}
            for question in exam.paper.paper_questions.all():
                question_stats[question.id] = {
                    'question': str(question.id),
                    'question_number': question.question_number,
                    'max_marks': question.marks,
                    'graded_attempt_count': 0,
                    'earned_marks_total': Decimal('0.00'),
                }
            for result in finalized:
                for item in result['questions']:
                    stat = question_stats[item['question']]
                    stat['graded_attempt_count'] += 1
                    stat['earned_marks_total'] += item['marks_awarded']
            for stat in question_stats.values():
                count = stat['graded_attempt_count']
                stat['average_marks'] = (
                    stat['earned_marks_total'] / count if count else None
                )
            results.append({
                'exam': str(exam.pk),
                'institute': str(exam.institute_id),
                'subject': str(exam.paper.subject_id),
                'batch': str(exam.batch_id),
                'exam_published': exam.published,
                'attempt_count': len(attempts_for_exam),
                'in_progress_attempt_count': in_progress,
                'pending_grading_count': pending,
                'other_attempt_count': other_attempts,
                'finalized_result_count': len(finalized),
                'average_marks': (
                    total_marks / len(finalized) if finalized else None
                ),
                'item_analysis': list(question_stats.values()),
            })
        return Response(results)
