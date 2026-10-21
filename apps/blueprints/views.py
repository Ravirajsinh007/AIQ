from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse

from apps.accounts.permissions import EnforcePasswordChange
from apps.accounts.models import RoleChoices, MembershipStatus
from .models import (
    PaperBlueprint,
    BlueprintSection,
    BlueprintRule,
    GeneratedPaper,
    BlueprintStatus,
    GeneratedPaperStatus,
)
from .permissions import CanManageBlueprints
from .serializers import (
    PaperBlueprintListSerializer,
    PaperBlueprintDetailSerializer,
    BlueprintSectionSerializer,
    BlueprintRuleSerializer,
    GeneratePaperRequestSerializer,
    GeneratedPaperListSerializer,
    GeneratedPaperDetailSerializer,
)
from .services import (
    PaperGenerationService,
    BlueprintValidationError,
    PaperGenerationError,
)
from .workflow import (
    archive_paper,
    create_paper_amendment,
    release_paper,
    review_paper,
    schedule_paper_release,
    submit_paper_for_review,
)
from .serializers import (
    PaperAmendmentSerializer,
    PaperRejectionSerializer,
    PaperReleaseScheduleSerializer,
)


class BlueprintChildAuditMixin:
    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save()
        self._record_child_audit(instance, 'created')

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        self._record_child_audit(instance, 'updated')

    @transaction.atomic
    def perform_destroy(self, instance):
        self._record_child_audit(instance, 'deleted')
        instance.delete()

    def _record_child_audit(self, instance, verb):
        from apps.audit.services import record_audit_event

        blueprint = instance.blueprint if hasattr(instance, 'blueprint') else instance.section.blueprint
        record_audit_event(
            action=f'blueprint_component.{instance._meta.model_name}.{verb}',
            resource_type=instance._meta.label_lower,
            resource_id=instance.pk,
            actor=self.request.user,
            institute=blueprint.institute,
        )


class PaperBlueprintViewSet(viewsets.ModelViewSet):
    """
    CRUD and actions for examination blueprints.
    Enforces institute scoping, teacher subject assignment checks,
    blueprint validation, and question availability reporting.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanManageBlueprints]
    filterset_fields = ['institute', 'subject', 'status', 'academic_year', 'semester', 'program', 'department']
    search_fields = ['title', 'subject__code', 'subject__name']
    ordering_fields = ['created_at', 'total_marks', 'title']

    def get_serializer_class(self):
        if self.action in ['retrieve', 'create', 'update', 'partial_update']:
            return PaperBlueprintDetailSerializer
        return PaperBlueprintListSerializer

    def get_queryset(self):
        user = getattr(self.request, 'user', None)
        if getattr(self, 'swagger_fake_view', False) or not user or not user.is_authenticated:
            return PaperBlueprint.objects.none()

        if user.is_platform_admin:
            return PaperBlueprint.objects.all().select_related(
                'institute', 'subject', 'academic_year', 'semester', 'program', 'department', 'created_by'
            ).prefetch_related('sections__rules')

        memberships = user.memberships.filter(
            status=MembershipStatus.ACTIVE,
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER],
        )
        manager_institutes = memberships.filter(
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF]
        ).values_list('institute_id', flat=True)
        return PaperBlueprint.objects.filter(
            Q(institute_id__in=manager_institutes)
            | Q(
                subject__teacher_assignments__teacher__user=user,
                subject__teacher_assignments__teacher__role=RoleChoices.TEACHER,
                subject__teacher_assignments__teacher__status=MembershipStatus.ACTIVE,
                subject__teacher_assignments__status='active',
            )
            | Q(created_by=user, institute__memberships__in=memberships)
        ).select_related(
            'institute', 'subject', 'academic_year', 'semester', 'program', 'department', 'created_by'
        ).prefetch_related('sections__rules').distinct()

    @transaction.atomic
    def perform_create(self, serializer):
        user = self.request.user
        membership = user.memberships.filter(
            institute=serializer.validated_data['institute'],
            status=MembershipStatus.ACTIVE
        ).first()
        if not user.is_platform_admin and (
            membership is None
            or membership.role not in [RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER]
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied('You are not authorized to manage blueprints for this institute.')

        # If user is a teacher, verify teaching assignment for this subject
        if membership and membership.role == RoleChoices.TEACHER:
            subj = serializer.validated_data['subject']
            is_assigned = membership.teaching_assignments.filter(
                subject=subj,
                status='active'
            ).exists()
            if not is_assigned:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("You can only create blueprints for subjects you are assigned to teach.")

        blueprint = serializer.save(created_by=user)
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='blueprint.created',
            resource_type='paper_blueprint',
            resource_id=blueprint.pk,
            actor=user,
            institute=blueprint.institute,
            metadata={'to_status': blueprint.status},
        )

    @transaction.atomic
    def perform_update(self, serializer):
        blueprint = self.get_object()
        changed_fields = sorted(serializer.validated_data.keys())
        blueprint = serializer.save()
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='blueprint.updated',
            resource_type='paper_blueprint',
            resource_id=blueprint.pk,
            actor=self.request.user,
            institute=blueprint.institute,
            metadata={'changed_fields': changed_fields},
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='blueprint.deleted',
            resource_type='paper_blueprint',
            resource_id=instance.pk,
            actor=self.request.user,
            institute=instance.institute,
        )
        instance.delete()

    @extend_schema(
        summary="Validate Blueprint Structure",
        description="Verifies section marks sum to total marks and rule counts are non-contradictory.",
        responses={200: OpenApiResponse(description="Validation results")}
    )
    @action(detail=True, methods=['get'], url_path='validate-structure')
    def validate_structure(self, request, pk=None):
        blueprint = self.get_object()
        try:
            report = PaperGenerationService.validate_blueprint_structure(blueprint)
            return Response(report, status=status.HTTP_200_OK)
        except BlueprintValidationError as e:
            return Response(
                {'error': {'message': e.message, 'details': e.details}},
                status=status.HTTP_400_BAD_REQUEST
            )

    @extend_schema(
        summary="Check Approved Question Availability",
        description="Checks M3 approved question bank for sufficient questions to satisfy blueprint rules.",
        responses={200: OpenApiResponse(description="Availability and shortage report")}
    )
    @action(detail=True, methods=['get'], url_path='check-availability')
    def check_availability(self, request, pk=None):
        blueprint = self.get_object()
        try:
            availability = PaperGenerationService.check_question_availability(blueprint)
            return Response(availability, status=status.HTTP_200_OK)
        except BlueprintValidationError as e:
            return Response(
                {'error': {'message': e.message, 'details': e.details}},
                status=status.HTTP_400_BAD_REQUEST
            )

    @extend_schema(
        summary="Generate Paper from Blueprint",
        description="Selects approved M3 questions according to blueprint rules and generates an immutable paper.",
        request=GeneratePaperRequestSerializer,
        responses={201: GeneratedPaperDetailSerializer}
    )
    @action(detail=True, methods=['post'], url_path='generate-paper')
    def generate_paper(self, request, pk=None):
        blueprint = self.get_object()
        user = request.user

        # Platform admin cannot generate papers on behalf of institutes
        if user.is_platform_admin:
            return Response(
                {'error': {'message': "Platform administrators cannot generate examination papers for institutes."}},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = GeneratePaperRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        custom_title = serializer.validated_data.get('title')

        try:
            paper = PaperGenerationService.generate_paper(
                blueprint=blueprint,
                user=user,
                custom_title=custom_title
            )
            return Response(
                GeneratedPaperDetailSerializer(paper).data,
                status=status.HTTP_201_CREATED
            )
        except BlueprintValidationError as e:
            return Response(
                {'error': {'message': e.message, 'details': e.details}},
                status=status.HTTP_400_BAD_REQUEST
            )
        except PaperGenerationError as e:
            return Response(
                {
                    'error': {
                        'message': e.message,
                        'details': e.shortage_report
                    }
                },
                status=status.HTTP_400_BAD_REQUEST
            )


class BlueprintSectionViewSet(BlueprintChildAuditMixin, viewsets.ModelViewSet):
    """
    CRUD API for blueprint sections.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanManageBlueprints]
    serializer_class = BlueprintSectionSerializer
    filterset_fields = ['blueprint']
    ordering_fields = ['order', 'target_marks']

    def get_queryset(self):
        user = getattr(self.request, 'user', None)
        if getattr(self, 'swagger_fake_view', False) or not user or not user.is_authenticated:
            return BlueprintSection.objects.none()

        if user.is_platform_admin:
            return BlueprintSection.objects.all().select_related('blueprint').prefetch_related('rules')

        memberships = user.memberships.filter(
            status=MembershipStatus.ACTIVE,
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER],
        )
        manager_institutes = memberships.filter(
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF]
        ).values_list('institute_id', flat=True)
        return BlueprintSection.objects.filter(
            Q(blueprint__institute_id__in=manager_institutes)
            | Q(
                blueprint__subject__teacher_assignments__teacher__user=user,
                blueprint__subject__teacher_assignments__teacher__role=RoleChoices.TEACHER,
                blueprint__subject__teacher_assignments__teacher__status=MembershipStatus.ACTIVE,
                blueprint__subject__teacher_assignments__status='active',
            )
            | Q(blueprint__created_by=user, blueprint__institute__memberships__in=memberships)
        ).select_related('blueprint').prefetch_related('rules').distinct()


class BlueprintRuleViewSet(BlueprintChildAuditMixin, viewsets.ModelViewSet):
    """
    CRUD API for blueprint section rules.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanManageBlueprints]
    serializer_class = BlueprintRuleSerializer
    filterset_fields = ['section', 'question_type', 'difficulty', 'bloom_taxonomy', 'unit', 'topic']
    ordering_fields = ['order', 'marks_per_question', 'question_count']

    def get_queryset(self):
        user = getattr(self.request, 'user', None)
        if getattr(self, 'swagger_fake_view', False) or not user or not user.is_authenticated:
            return BlueprintRule.objects.none()

        if user.is_platform_admin:
            return BlueprintRule.objects.all().select_related(
                'section__blueprint', 'unit', 'topic', 'learning_outcome'
            )

        memberships = user.memberships.filter(
            status=MembershipStatus.ACTIVE,
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER],
        )
        manager_institutes = memberships.filter(
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF]
        ).values_list('institute_id', flat=True)
        return BlueprintRule.objects.filter(
            Q(section__blueprint__institute_id__in=manager_institutes)
            | Q(
                section__blueprint__subject__teacher_assignments__teacher__user=user,
                section__blueprint__subject__teacher_assignments__teacher__role=RoleChoices.TEACHER,
                section__blueprint__subject__teacher_assignments__teacher__status=MembershipStatus.ACTIVE,
                section__blueprint__subject__teacher_assignments__status='active',
            )
            | Q(section__blueprint__created_by=user, section__blueprint__institute__memberships__in=memberships)
        ).select_related('section__blueprint', 'unit', 'topic', 'learning_outcome').distinct()


class GeneratedPaperViewSet(viewsets.ReadOnlyModelViewSet):
    """
    List and retrieve generated papers.
    Includes validation reports, question counts, and immutable snapshots.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanManageBlueprints]
    filterset_fields = ['institute', 'blueprint', 'subject', 'status']
    search_fields = ['title', 'subject__code', 'subject__name']
    ordering_fields = ['created_at', 'total_marks', 'generation_version']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return GeneratedPaperDetailSerializer
        return GeneratedPaperListSerializer

    def get_queryset(self):
        user = getattr(self.request, 'user', None)
        if getattr(self, 'swagger_fake_view', False) or not user or not user.is_authenticated:
            return GeneratedPaper.objects.none()

        if user.is_platform_admin:
            return GeneratedPaper.objects.all().select_related(
                'institute', 'blueprint', 'subject', 'created_by'
            ).prefetch_related('paper_questions')

        memberships = user.memberships.filter(
            status=MembershipStatus.ACTIVE,
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF, RoleChoices.TEACHER],
        )
        manager_institutes = memberships.filter(
            role__in=[RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF]
        ).values_list('institute_id', flat=True)
        return GeneratedPaper.objects.filter(
            Q(institute_id__in=manager_institutes)
            | Q(
                subject__teacher_assignments__teacher__user=user,
                subject__teacher_assignments__teacher__role=RoleChoices.TEACHER,
                subject__teacher_assignments__teacher__status=MembershipStatus.ACTIVE,
                subject__teacher_assignments__status='active',
            )
            | Q(created_by=user, institute__memberships__in=memberships)
        ).select_related(
            'institute', 'blueprint', 'subject', 'created_by'
        ).prefetch_related('paper_questions').distinct()

    @extend_schema(summary='Submit generated paper for formal review', responses={200: GeneratedPaperDetailSerializer})
    @action(detail=True, methods=['post'], url_path='submit-review')
    def submit_review(self, request, pk=None):
        paper = submit_paper_for_review(self.get_object().pk, request.user)
        return Response(GeneratedPaperDetailSerializer(paper).data)

    @extend_schema(summary='Approve generated paper', responses={200: GeneratedPaperDetailSerializer})
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        paper = review_paper(self.get_object().pk, request.user, approve=True)
        return Response(GeneratedPaperDetailSerializer(paper).data)

    @extend_schema(
        summary='Reject generated paper',
        request=PaperRejectionSerializer,
        responses={200: GeneratedPaperDetailSerializer},
    )
    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        serializer = PaperRejectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        paper = review_paper(
            self.get_object().pk,
            request.user,
            approve=False,
            rejection_reason=serializer.validated_data['rejection_reason'],
        )
        return Response(GeneratedPaperDetailSerializer(paper).data)

    @extend_schema(
        summary='Schedule release of an approved generated paper',
        request=PaperReleaseScheduleSerializer,
        responses={200: GeneratedPaperDetailSerializer},
    )
    @action(detail=True, methods=['post'], url_path='schedule-release')
    def schedule_release(self, request, pk=None):
        serializer = PaperReleaseScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        paper = schedule_paper_release(
            self.get_object().pk,
            request.user,
            serializer.validated_data['release_at'],
        )
        return Response(GeneratedPaperDetailSerializer(paper).data)

    @extend_schema(summary='Release a scheduled paper when its release time has arrived')
    @action(detail=True, methods=['post'], url_path='release')
    def release(self, request, pk=None):
        paper = release_paper(self.get_object().pk, user=request.user)
        return Response(GeneratedPaperDetailSerializer(paper).data)

    @extend_schema(
        summary='Create a traceable draft amendment of an immutable paper version',
        request=PaperAmendmentSerializer,
        responses={201: GeneratedPaperDetailSerializer},
    )
    @action(detail=True, methods=['post'], url_path='amend')
    def amend(self, request, pk=None):
        serializer = PaperAmendmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        paper = create_paper_amendment(
            self.get_object().pk,
            request.user,
            title=serializer.validated_data.get('title', ''),
            reason=serializer.validated_data['reason'],
            question_edits=serializer.validated_data.get('question_edits', []),
        )
        return Response(GeneratedPaperDetailSerializer(paper).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary='Archive a paper version')
    @action(detail=True, methods=['post'], url_path='archive')
    def archive(self, request, pk=None):
        paper = archive_paper(self.get_object().pk, request.user)
        return Response(GeneratedPaperDetailSerializer(paper).data)
