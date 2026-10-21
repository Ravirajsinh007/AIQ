from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse

from apps.accounts.models import RoleChoices, MembershipStatus
from apps.accounts.permissions import EnforcePasswordChange
from apps.questions.models import Question, QuestionStatus, QuestionType
from apps.questions.serializers import QuestionSerializer
from .models import QuestionReviewRecord, ReviewDecision
from .permissions import CanReviewQuestions
from .serializers import (
    QuestionReviewRecordSerializer,
    QuestionReviewDetailSerializer,
    SubmitForReviewActionSerializer,
    ApproveQuestionActionSerializer,
    RejectQuestionActionSerializer,
    RequestRevisionActionSerializer,
    ArchiveQuestionActionSerializer,
)


class QuestionReviewWorkflowViewSet(viewsets.GenericViewSet):
    """
    Dedicated Module M5 Workflow ViewSet for reviewing questions.
    Provides strict state transition enforcement, anti-self-approval protection,
    reviewer feedback capture, and comprehensive review history.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanReviewQuestions]
    queryset = Question.objects.all()

    def get_queryset(self):
        user = getattr(self.request, 'user', None)
        if getattr(self, 'swagger_fake_view', False) or not user or not user.is_authenticated:
            return Question.objects.none()

        if user.is_platform_admin:
            return Question.objects.all().select_related(
                'institute', 'subject', 'unit', 'topic', 'learning_outcome', 'created_by'
            ).prefetch_related('options', 'rubrics', 'source_references', 'tags', 'verification_reviews')

        memberships = user.memberships.filter(
            status=MembershipStatus.ACTIVE,
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER],
        )
        institute_ids = memberships.values_list('institute_id', flat=True)
        return Question.objects.filter(institute_id__in=institute_ids).select_related(
            'institute', 'subject', 'unit', 'topic', 'learning_outcome', 'created_by'
        ).prefetch_related('options', 'rubrics', 'source_references', 'tags', 'verification_reviews')

    def _get_active_membership(self, institute):
        return self.request.user.memberships.filter(
            institute=institute,
            status=MembershipStatus.ACTIVE
        ).first()

    @extend_schema(
        summary="List Questions Pending Review",
        description="Returns list of questions currently under review within the user's institute.",
        responses={200: QuestionSerializer(many=True)}
    )
    @action(detail=False, methods=['get'], url_path='pending')
    def pending_reviews(self, request):
        qs = self.get_queryset().filter(status=QuestionStatus.UNDER_REVIEW).order_by('-updated_at')
        
        # Filter by subject if requested
        subject_id = request.query_params.get('subject')
        if subject_id:
            qs = qs.filter(subject_id=subject_id)

        # Pagination support
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = QuestionSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = QuestionSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Get Comprehensive Question Review Package",
        description="Inspect complete question details, answer keys, options, rubrics, provenance, version history, and review history.",
        responses={200: QuestionReviewDetailSerializer}
    )
    @action(detail=True, methods=['get'], url_path='inspection')
    def inspection(self, request, pk=None):
        question = self.get_object()
        serializer = QuestionReviewDetailSerializer(question)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Submit Question For Review",
        description="Transitions a question from draft or rejected back to under_review.",
        request=SubmitForReviewActionSerializer,
        responses={200: QuestionSerializer}
    )
    @action(detail=True, methods=['post'], url_path='submit')
    def submit_for_review(self, request, pk=None):
        question = self.get_object()
        user = request.user

        serializer = SubmitForReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notes = serializer.validated_data.get('notes', '')
        from .services import submit_question_for_review

        try:
            submit_question_for_review(question=question, user=user, notes=notes)
        except (ValidationError, PermissionDenied, NotFound) as exc:
            return Response({'error': {'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST if isinstance(exc, ValidationError) else status.HTTP_403_FORBIDDEN if isinstance(exc, PermissionDenied) else status.HTTP_404_NOT_FOUND)

        return Response(
            {
                'message': 'Question successfully submitted for review.',
                'question': QuestionSerializer(question).data
            },
            status=status.HTTP_200_OK
        )

    @extend_schema(
        summary="Approve Question",
        description="Approves a question currently under review. Enforces strict anti-self-approval: authors cannot approve their own questions.",
        request=ApproveQuestionActionSerializer,
        responses={200: QuestionSerializer}
    )
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        question = self.get_object()
        user = request.user

        # Platform admins cannot make institutional review decisions
        if user.is_platform_admin:
            return Response(
                {'error': {'message': "Platform administrators cannot approve questions on behalf of institutes."}},
                status=status.HTTP_403_FORBIDDEN
            )

        membership = self._get_active_membership(question.institute)
        if not membership or membership.role not in [RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER]:
            return Response(
                {'error': {'message': "You do not have reviewer privileges for this institute."}},
                status=status.HTTP_403_FORBIDDEN
            )

        # Strict Anti-Self-Approval: Author cannot approve their own question!
        if question.created_by_id == user.id:
            return Response(
                {
                    'error': {
                        'message': "Authors cannot approve their own questions. Another authorized reviewer or administrator must conduct the review."
                    }
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # State Transition Check: Must be UNDER_REVIEW
        if question.status != QuestionStatus.UNDER_REVIEW:
            return Response(
                {
                    'error': {
                        'message': f"Cannot approve question in status '{question.status}'. Question must be in '{QuestionStatus.UNDER_REVIEW}'."
                    }
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verification of question completeness
        if question.question_type == QuestionType.MCQ:
            if question.options.count() < 2 or not question.options.filter(is_correct=True).exists():
                return Response(
                    {'error': {'message': "Question fails verification: MCQ must have at least 2 options and a correct answer marked."}},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif question.question_type == QuestionType.TRUE_FALSE:
            if question.options.count() != 2 or question.options.filter(is_correct=True).count() != 1:
                return Response(
                    {'error': {'message': "Question fails verification: True/False must have exactly 2 options and exactly 1 correct answer."}},
                    status=status.HTTP_400_BAD_REQUEST
                )

        serializer = ApproveQuestionActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notes = serializer.validated_data.get('notes', '')
        rubric_scores = serializer.validated_data.get('rubric_scores', {})

        with transaction.atomic():
            old_status = question.status
            question.status = QuestionStatus.APPROVED
            question.save(update_fields=['status', 'updated_at'])

            review_record = QuestionReviewRecord.objects.create(
                question=question,
                reviewer=user,
                decision=ReviewDecision.APPROVE,
                from_status=old_status,
                to_status=QuestionStatus.APPROVED,
                general_notes=notes or "Approved by reviewer",
                rubric_scores=rubric_scores,
                question_version=question.current_version
            )
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='question.approved',
                resource_type='question',
                resource_id=question.pk,
                actor=user,
                institute=question.institute,
                metadata={'from_status': old_status, 'to_status': question.status},
            )

        return Response(
            {
                'message': 'Question successfully approved.',
                'question': QuestionSerializer(question).data,
                'review_record': QuestionReviewRecordSerializer(review_record).data
            },
            status=status.HTTP_200_OK
        )

    @extend_schema(
        summary="Reject Question",
        description="Rejects a question currently under review. Requires a clear rejection reason.",
        request=RejectQuestionActionSerializer,
        responses={200: QuestionSerializer}
    )
    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        question = self.get_object()
        user = request.user

        if user.is_platform_admin:
            return Response(
                {'error': {'message': "Platform administrators cannot reject questions on behalf of institutes."}},
                status=status.HTTP_403_FORBIDDEN
            )

        membership = self._get_active_membership(question.institute)
        if not membership or membership.role not in [RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER]:
            return Response(
                {'error': {'message': "You do not have reviewer privileges for this institute."}},
                status=status.HTTP_403_FORBIDDEN
            )

        # Anti-Self-Review: author should not reject their own question; they can delete or edit it
        if question.created_by_id == user.id and membership.role == RoleChoices.TEACHER:
            return Response(
                {'error': {'message': "Teachers cannot perform review rejections on their own questions."}},
                status=status.HTTP_403_FORBIDDEN
            )

        # State Transition Check: Must be UNDER_REVIEW
        if question.status != QuestionStatus.UNDER_REVIEW:
            return Response(
                {
                    'error': {
                        'message': f"Cannot reject question in status '{question.status}'. Question must be in '{QuestionStatus.UNDER_REVIEW}'."
                    }
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = RejectQuestionActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rejection_reason = serializer.validated_data['rejection_reason']
        notes = serializer.validated_data.get('notes', '')

        with transaction.atomic():
            old_status = question.status
            question.status = QuestionStatus.REJECTED
            question.save(update_fields=['status', 'updated_at'])

            review_record = QuestionReviewRecord.objects.create(
                question=question,
                reviewer=user,
                decision=ReviewDecision.REJECT,
                from_status=old_status,
                to_status=QuestionStatus.REJECTED,
                rejection_reason=rejection_reason,
                general_notes=notes,
                question_version=question.current_version
            )
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='question.rejected',
                resource_type='question',
                resource_id=question.pk,
                actor=user,
                institute=question.institute,
                metadata={'from_status': old_status, 'to_status': question.status},
            )

        return Response(
            {
                'message': 'Question rejected.',
                'question': QuestionSerializer(question).data,
                'review_record': QuestionReviewRecordSerializer(review_record).data
            },
            status=status.HTTP_200_OK
        )

    @extend_schema(
        summary="Request Revisions on Question",
        description="Returns question to draft status with specific feedback for the author to address.",
        request=RequestRevisionActionSerializer,
        responses={200: QuestionSerializer}
    )
    @action(detail=True, methods=['post'], url_path='request-revision')
    def request_revision(self, request, pk=None):
        question = self.get_object()
        user = request.user

        if user.is_platform_admin:
            return Response(
                {'error': {'message': "Platform administrators cannot request revisions on behalf of institutes."}},
                status=status.HTTP_403_FORBIDDEN
            )

        membership = self._get_active_membership(question.institute)
        if not membership or membership.role not in [RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER]:
            return Response(
                {'error': {'message': "You do not have reviewer privileges for this institute."}},
                status=status.HTTP_403_FORBIDDEN
            )

        if question.created_by_id == user.id and membership.role == RoleChoices.TEACHER:
            return Response(
                {'error': {'message': "Teachers cannot request revisions on their own questions."}},
                status=status.HTTP_403_FORBIDDEN
            )

        # State Transition Check: Must be UNDER_REVIEW
        if question.status != QuestionStatus.UNDER_REVIEW:
            return Response(
                {
                    'error': {
                        'message': f"Cannot request revision for question in status '{question.status}'. Question must be in '{QuestionStatus.UNDER_REVIEW}'."
                    }
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = RequestRevisionActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        revision_feedback = serializer.validated_data['revision_feedback']
        notes = serializer.validated_data.get('notes', '')

        with transaction.atomic():
            old_status = question.status
            # Return to draft so the author can edit and resubmit
            question.status = QuestionStatus.DRAFT
            question.save(update_fields=['status', 'updated_at'])

            review_record = QuestionReviewRecord.objects.create(
                question=question,
                reviewer=user,
                decision=ReviewDecision.REQUEST_REVISION,
                from_status=old_status,
                to_status=QuestionStatus.DRAFT,
                revision_feedback=revision_feedback,
                general_notes=notes,
                question_version=question.current_version
            )
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='question.revision_requested',
                resource_type='question',
                resource_id=question.pk,
                actor=user,
                institute=question.institute,
                metadata={'from_status': old_status, 'to_status': question.status},
            )

        return Response(
            {
                'message': 'Revision requested. Question returned to draft status.',
                'question': QuestionSerializer(question).data,
                'review_record': QuestionReviewRecordSerializer(review_record).data
            },
            status=status.HTTP_200_OK
        )

    @extend_schema(
        summary="Archive Question",
        description="Archives an approved or rejected question. Only institute administrators or exam staff can archive questions.",
        request=ArchiveQuestionActionSerializer,
        responses={200: QuestionSerializer}
    )
    @action(detail=True, methods=['post'], url_path='archive')
    def archive(self, request, pk=None):
        question = self.get_object()
        user = request.user

        membership = self._get_active_membership(question.institute)
        if not membership or membership.role not in [RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF]:
            return Response(
                {'error': {'message': "Only Institute Administrators or Examination Staff can archive questions."}},
                status=status.HTTP_403_FORBIDDEN
            )

        # Cannot archive if currently under review
        if question.status == QuestionStatus.UNDER_REVIEW:
            return Response(
                {'error': {'message': "Cannot archive a question while it is actively under review. Complete review first."}},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ArchiveQuestionActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get('reason', '')

        with transaction.atomic():
            old_status = question.status
            question.status = QuestionStatus.ARCHIVED
            question.save(update_fields=['status', 'updated_at'])

            review_record = QuestionReviewRecord.objects.create(
                question=question,
                reviewer=user,
                decision=ReviewDecision.REJECT,
                from_status=old_status,
                to_status=QuestionStatus.ARCHIVED,
                general_notes=reason or "Archived by administrator",
                question_version=question.current_version
            )
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='question.archived',
                resource_type='question',
                resource_id=question.pk,
                actor=user,
                institute=question.institute,
                metadata={'from_status': old_status, 'to_status': question.status},
            )

        return Response(
            {
                'message': 'Question successfully archived.',
                'question': QuestionSerializer(question).data,
                'review_record': QuestionReviewRecordSerializer(review_record).data
            },
            status=status.HTTP_200_OK
        )


class QuestionReviewRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only audit log of all verification reviews across an institute.
    Allows filtering by question, reviewer, decision, and date.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanReviewQuestions]
    serializer_class = QuestionReviewRecordSerializer
    filterset_fields = ['question', 'reviewer', 'decision', 'from_status', 'to_status']
    ordering_fields = ['created_at', 'question_version']
    queryset = QuestionReviewRecord.objects.all()

    def get_queryset(self):
        user = getattr(self.request, 'user', None)
        if getattr(self, 'swagger_fake_view', False) or not user or not user.is_authenticated:
            return QuestionReviewRecord.objects.none()

        if user.is_platform_admin:
            return QuestionReviewRecord.objects.all().select_related('question', 'reviewer', 'question__institute')

        memberships = user.memberships.filter(
            status=MembershipStatus.ACTIVE,
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER],
        )
        institute_ids = memberships.values_list('institute_id', flat=True)
        return QuestionReviewRecord.objects.filter(
            question__institute_id__in=institute_ids
        ).select_related('question', 'reviewer', 'question__institute')
