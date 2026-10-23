from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse
from apps.accounts.permissions import EnforcePasswordChange
from .permissions import CanManageQuestions
from .models import (
    Question,
    QuestionTag,
    QuestionVersion,
    QuestionSourceReference,
    QuestionReview,
    QuestionStatus,
)
from .serializers import (
    QuestionSerializer,
    QuestionCreateUpdateSerializer,
    QuestionTagSerializer,
    QuestionVersionSerializer,
    QuestionSourceReferenceSerializer,
    QuestionReviewSerializer,
)


def _require_question_scope(user, institute_id, subject):
    from rest_framework.exceptions import PermissionDenied

    if user.is_platform_admin:
        return
    membership = user.memberships.filter(
        institute_id=institute_id,
        status='active',
        role__in=['institute_admin', 'exam_staff'],
    ).first()
    if membership is not None:
        return
    teacher_membership = user.memberships.filter(
        institute_id=institute_id,
        status='active',
        role='teacher',
    ).first()
    if teacher_membership is None:
        raise PermissionDenied('You are not authorized to manage questions for this institute.')
    if not teacher_membership.teaching_assignments.filter(
        subject=subject,
        status='active',
    ).exists():
        raise PermissionDenied('Teachers can manage questions only for subjects they are actively assigned to teach.')


class QuestionViewSet(viewsets.ModelViewSet):
    """
    Question Bank API supporting MCQ, True/False, Short Answer,
    Long Answer, and Coding question management.
    Enforces institute tenant isolation, teacher assignment checks,
    and automatic immutable version snapshotting on update.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanManageQuestions]
    filterset_fields = [
        'institute', 'subject', 'unit', 'topic', 'learning_outcome',
        'question_type', 'difficulty', 'status', 'bloom_taxonomy', 'origin_type'
    ]
    search_fields = ['question_text']
    ordering_fields = ['created_at', 'marks', 'difficulty', 'current_version']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return QuestionCreateUpdateSerializer
        return QuestionSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return Question.objects.all().select_related(
                'institute', 'subject', 'unit', 'topic', 'learning_outcome', 'created_by'
            ).prefetch_related('options', 'rubrics', 'source_references', 'tags')

        manager_memberships = user.memberships.filter(
            status='active',
            role__in=['institute_admin', 'exam_staff'],
        )
        institute_ids = manager_memberships.values_list('institute_id', flat=True)
        teacher_subjects = user.memberships.filter(
            status='active',
            role='teacher',
            teaching_assignments__status='active',
        ).values_list('teaching_assignments__subject_id', flat=True)
        return Question.objects.filter(
            Q(institute_id__in=institute_ids) | Q(subject_id__in=teacher_subjects)
        ).distinct().select_related(
            'institute', 'subject', 'unit', 'topic', 'learning_outcome', 'created_by'
        ).prefetch_related('options', 'rubrics', 'source_references', 'tags')

    @extend_schema(summary="List Questions", responses={200: QuestionSerializer(many=True)})
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Create Question (Defaults to Draft)", responses={201: QuestionSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _require_question_scope(
            request.user,
            serializer.validated_data['institute'].id,
            serializer.validated_data['subject'],
        )
        question = serializer.save()
        return Response(QuestionSerializer(question).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Update Question (Creates Version Snapshot)", responses={200: QuestionSerializer})
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated_question = serializer.save()
        return Response(QuestionSerializer(updated_question).data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Get Question Version History",
        responses={200: QuestionVersionSerializer(many=True)}
    )
    @action(detail=True, methods=['get'], url_path='versions')
    def versions(self, request, pk=None):
        question = self.get_object()
        versions = question.versions.all().order_by('-version_number')
        serializer = QuestionVersionSerializer(versions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Get Question Source References (Provenance)",
        responses={200: QuestionSourceReferenceSerializer(many=True)}
    )
    @action(detail=True, methods=['get'], url_path='source-references')
    def source_references(self, request, pk=None):
        question = self.get_object()
        sources = question.source_references.all().order_by('-created_at')
        serializer = QuestionSourceReferenceSerializer(sources, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Submit Question For Review",
        responses={200: OpenApiResponse(description="Question submitted for review")}
    )
    @action(detail=True, methods=['post'], url_path='submit-for-review')
    def submit_for_review(self, request, pk=None):
        question = self.get_object()
        if question.status != QuestionStatus.DRAFT:
            return Response(
                {'error': {'message': f"Only questions in draft status can be submitted for review. Current status: {question.status}"}},
                status=status.HTTP_400_BAD_REQUEST
            )
        from apps.reviews.services import submit_question_for_review

        submit_question_for_review(
            question=question,
            user=request.user,
            notes=request.data.get('notes', ''),
        )
        return Response(
            {'message': 'Question submitted for review successfully.', 'question': QuestionSerializer(question).data},
            status=status.HTTP_200_OK
        )


class QuestionTagViewSet(viewsets.ModelViewSet):
    """
    CRUD API for Question Tags scoped to user's institute.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanManageQuestions]
    serializer_class = QuestionTagSerializer
    filterset_fields = ['institute']
    search_fields = ['name']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return QuestionTag.objects.all().select_related('institute')
        user_institutes = user.memberships.filter(
            status='active',
            role__in=['institute_admin', 'teacher', 'exam_staff'],
        ).values_list('institute_id', flat=True)
        return QuestionTag.objects.filter(institute_id__in=user_institutes).select_related('institute')

    def perform_create(self, serializer):
        from rest_framework.exceptions import PermissionDenied

        institute = serializer.validated_data['institute']
        if not self.request.user.is_platform_admin and not self.request.user.memberships.filter(
            institute=institute,
            status='active',
            role__in=['institute_admin', 'teacher', 'exam_staff'],
        ).exists():
            raise PermissionDenied('You are not authorized to manage tags for this institute.')
        serializer.save()


class QuestionReviewViewSet(viewsets.ModelViewSet):
    """
    Captures review decisions and comments on questions.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanManageQuestions]
    serializer_class = QuestionReviewSerializer
    filterset_fields = ['question', 'decision']
    ordering_fields = ['created_at']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return QuestionReview.objects.all().select_related('question', 'reviewer')
        memberships = user.memberships.filter(
            status='active',
            role__in=['institute_admin', 'teacher', 'exam_staff'],
        )
        manager_institutes = memberships.filter(
            role__in=['institute_admin', 'exam_staff']
        ).values_list('institute_id', flat=True)
        return QuestionReview.objects.filter(
            Q(question__institute_id__in=manager_institutes)
            | Q(
                question__subject__teacher_assignments__teacher__user=user,
                question__subject__teacher_assignments__teacher__role='teacher',
                question__subject__teacher_assignments__teacher__status='active',
                question__subject__teacher_assignments__status='active',
            )
        ).select_related('question', 'reviewer').distinct()

    def perform_create(self, serializer):
        question = serializer.validated_data['question']
        _require_question_scope(self.request.user, question.institute_id, question.subject)
        from apps.reviews.services import apply_question_review_decision

        apply_question_review_decision(serializer=serializer, user=self.request.user)
